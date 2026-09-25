"""One disposable SSH checker, supervised independently of remote I/O.

Credentials travel only over stdin. The child returns a bounded snapshot or a
credential-free error code. No BootAgent, swarm keys or temporary key files are
needed in the child. This file is also its isolated Python entry point.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time


MAX_REQUEST = 65_536
MAX_SNAPSHOT = 1_048_576
MAX_RESPONSE = MAX_SNAPSHOT * 6 + 1_024  # JSON escaping overhead
ERROR_CODES = frozenset({
    "SSH_TIMEOUT", "SSH_AUTH_FAILED", "SSH_HOST_KEY_MISMATCH",
    "SSH_DNS_ERROR", "SSH_CONNECTION_FAILED", "SSH_PROTOCOL_ERROR",
    "SSH_CONFIG_ERROR", "MATRIXD_CHECK_FAILED", "SSH_WORKER_FAILED",
    "SSH_CHECK_BUSY", "SSH_CLEANUP_FAILED",
})


class SSHCheckError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in ERROR_CODES else "SSH_WORKER_FAILED"
        super().__init__(self.code)


class SSHCheckCancelled(Exception):
    """Agent shutdown is not a failed observation of the remote hive."""


class SSHCheckRunner:
    """Own at most one child and its pipe-draining thread until both exit."""

    POLL_SECONDS = 0.2
    CLEANUP_SECONDS = 1.0

    def __init__(self):
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._process = None
        self._io_thread = None

    def run(self, profile, timeout, *, pulse, cancelled):
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 2 <= timeout <= 300:
            raise SSHCheckError("SSH_CONFIG_ERROR")
        try:
            request = json.dumps({"ssh": profile, "timeout": timeout}).encode("utf-8")
        except (TypeError, ValueError):
            raise SSHCheckError("SSH_CONFIG_ERROR") from None
        if len(request) > MAX_REQUEST:
            raise SSHCheckError("SSH_CONFIG_ERROR")
        command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), str(os.getpid())]
        response = self._run_process(command, request, timeout, pulse, cancelled)
        try:
            result = json.loads(response)
            if not isinstance(result, dict):
                raise ValueError("invalid result")
            if result.get("ok") is not True:
                raise SSHCheckError(result.get("error"))
            snapshot = result["snapshot"]
            if not isinstance(snapshot, str) or len(snapshot.encode("utf-8")) > MAX_SNAPSHOT:
                raise ValueError("invalid snapshot")
            return snapshot
        except (KeyError, TypeError, ValueError, UnicodeError):
            raise SSHCheckError("SSH_WORKER_FAILED") from None

    def _run_process(self, command, request, timeout, pulse, cancelled):
        if not self._lock.acquire(blocking=False):
            raise SSHCheckError("SSH_CHECK_BUSY")
        try:
            # A failed reap never frees the slot for another child.
            self._cleanup()
            if self._stopped.is_set() or cancelled():
                raise SSHCheckCancelled()
            deadline = time.monotonic() + timeout
            env = {key: value for key, value in os.environ.items() if key.upper() in {
                "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
                "LANG", "LC_ALL", "LC_CTYPE", "SSH_AUTH_SOCK",
            }}
            self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, shell=False, close_fds=True, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            process = self._process
            completed = threading.Event()
            result = {}

            def exchange():
                try:
                    result["output"], _ = process.communicate(input=request)
                except Exception:
                    result["error"] = True
                finally:
                    result["finished_at"] = time.monotonic()
                    completed.set()

            # On Windows a blocking stdin write is not bounded by communicate's
            # timeout. Keep all pipe I/O off the supervising/beacon thread too.
            self._io_thread = threading.Thread(
                target=exchange, name="harvester-ssh-pipes", daemon=True
            )
            self._io_thread.start()
            while True:
                if self._stopped.is_set() or cancelled():
                    raise SSHCheckCancelled()
                pulse()
                if completed.is_set():
                    if result["finished_at"] > deadline:
                        raise SSHCheckError("SSH_TIMEOUT")
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SSHCheckError("SSH_TIMEOUT")
                completed.wait(min(self.POLL_SECONDS, remaining))
            output = result.get("output", b"")
            if result.get("error") or process.returncode != 0 or len(output) > MAX_RESPONSE:
                raise SSHCheckError("SSH_WORKER_FAILED")
            return output
        except OSError:
            raise SSHCheckError("SSH_WORKER_FAILED") from None
        finally:
            try:
                self._cleanup()
            finally:
                self._lock.release()

    def _cleanup(self):
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=self.CLEANUP_SECONDS)
            if self._io_thread is not None and self._io_thread.ident is not None:
                self._io_thread.join(timeout=self.CLEANUP_SECONDS)
                if self._io_thread.is_alive():
                    raise SSHCheckError("SSH_CLEANUP_FAILED")
        except (OSError, subprocess.TimeoutExpired):
            raise SSHCheckError("SSH_CLEANUP_FAILED") from None
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()
        self._process = None
        self._io_thread = None

    def close(self):
        self._stopped.set()
        if not self._lock.acquire(timeout=self.CLEANUP_SECONDS * 3):
            raise SSHCheckError("SSH_CLEANUP_FAILED")
        try:
            self._cleanup()
        finally:
            self._lock.release()


def _protect_child(parent_pid):
    if sys.platform.startswith("linux"):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        # Protect credentials after exec, and don't outlive an abruptly exiting
        # parent (BootAgent can use os._exit rather than graceful shutdown).
        if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            raise RuntimeError("memory protection unavailable")
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise RuntimeError("parent-death protection unavailable")
        if os.getppid() != parent_pid:
            raise RuntimeError("parent exited")


def _error_code(exc, transport):
    paramiko = transport.paramiko
    if isinstance(exc, (transport.HostKeyMismatch, paramiko.BadHostKeyException)):
        return "SSH_HOST_KEY_MISMATCH"
    if isinstance(exc, paramiko.AuthenticationException):
        return "SSH_AUTH_FAILED"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "SSH_TIMEOUT"
    if isinstance(exc, socket.gaierror):
        return "SSH_DNS_ERROR"
    if isinstance(exc, (OSError, EOFError)):
        return "SSH_CONNECTION_FAILED"
    if isinstance(exc, paramiko.SSHException):
        return "SSH_PROTOCOL_ERROR"
    if isinstance(exc, (TypeError, ValueError)):
        return "SSH_CONFIG_ERROR"
    if isinstance(exc, RuntimeError):
        return "MATRIXD_CHECK_FAILED"
    return "SSH_WORKER_FAILED"


def _child_main():
    result = {"ok": False, "error": "SSH_WORKER_FAILED"}
    try:
        _protect_child(int(sys.argv[1]))
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise ValueError("oversized request")
        request = json.loads(raw)
        profile, timeout = request["ssh"], request["timeout"]
        if not isinstance(profile, dict) or type(timeout) is not int or not 2 <= timeout <= 300:
            raise ValueError("invalid request")
        # -I excludes working-directory/PYTHONPATH imports. Load only the sibling
        # transport source and installed dependencies from this interpreter.
        spec = importlib.util.spec_from_file_location(
            "harvester_check_transport", Path(__file__).with_name("ssh_transport.py")
        )
        transport = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(transport)
        try:
            snapshot = transport.run_matrixd_list(profile, timeout, MAX_SNAPSHOT)
            result = {"ok": True, "snapshot": snapshot}
        except Exception as exc:
            result = {"ok": False, "error": _error_code(exc, transport)}
    except Exception:
        pass  # Never serialize exception messages, keys or server stderr.
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    sys.stdout.flush()


if __name__ == "__main__":
    _child_main()
