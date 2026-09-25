"""Real disposable-child tests; no production host or credentials are used."""

import base64
from hashlib import sha256
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

from tests.test_harvester_policy import CHECK, SSH


class HarvesterSSHCheckTests(unittest.TestCase):
    def setUp(self):
        self.runner = CHECK.SSHCheckRunner()
        self.addCleanup(self.runner.close)

    def run_child(self, script, *, request=b"{}", timeout=2, pulse=None, cancelled=None):
        return self.runner._run_process(
            [sys.executable, "-I", "-B", "-c", script], request, timeout,
            pulse or (lambda: None), cancelled or (lambda: False),
        )

    def test_real_child_exits_and_is_reaped(self):
        pulse = Mock()
        output = self.run_child("import sys; print(sys.stdin.buffer.read().decode())", pulse=pulse)
        self.assertEqual(output.strip(), b"{}")
        pulse.assert_called()
        self.assertIsNone(self.runner._process)
        self.assertIsNone(self.runner._io_thread)

    def test_deadline_kills_hung_child_keeps_beacon_and_allows_next_check(self):
        seen, pulses = [], []
        def pulse():
            seen.append(self.runner._process)
            pulses.append(time.monotonic())
        started = time.monotonic()
        with self.assertRaises(CHECK.SSHCheckError) as caught:
            self.run_child("import time; time.sleep(30)", timeout=0.7, pulse=pulse)
        self.assertEqual(caught.exception.code, "SSH_TIMEOUT")
        self.assertLess(time.monotonic() - started, 4)
        self.assertGreaterEqual(len(pulses), 3)
        self.assertIsNotNone(seen[0].poll())
        self.assertIsNone(self.runner._process)
        self.assertIsNone(self.runner._io_thread)
        self.assertEqual(self.run_child("print('next')").strip(), b"next")

    def test_blocked_stdin_cannot_stall_supervisor(self):
        with self.assertRaises(CHECK.SSHCheckError) as caught:
            self.run_child("import time; time.sleep(30)", request=b"x" * CHECK.MAX_REQUEST, timeout=0.5)
        self.assertEqual(caught.exception.code, "SSH_TIMEOUT")
        self.assertIsNone(self.runner._io_thread)

    def test_cancel_stops_child_and_discards_late_result(self):
        pulses = []
        with self.assertRaises(CHECK.SSHCheckCancelled):
            self.run_child(
                "import time; time.sleep(30); print('late healthy')",
                pulse=lambda: pulses.append(1), cancelled=lambda: len(pulses) >= 2,
            )
        self.assertIsNone(self.runner._process)

    def test_cannot_start_overlapping_check(self):
        self.runner._lock.acquire()
        try:
            with patch.object(CHECK.subprocess, "Popen") as popen:
                with self.assertRaises(CHECK.SSHCheckError) as caught:
                    self.runner.run({}, 2, pulse=lambda: None, cancelled=lambda: False)
                popen.assert_not_called()
            self.assertEqual(caught.exception.code, "SSH_CHECK_BUSY")
        finally:
            self.runner._lock.release()

    def test_failed_reap_retains_slot_and_blocks_replacement(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("checker", 1)
        self.runner._process = process
        with patch.object(CHECK.subprocess, "Popen") as popen:
            with self.assertRaises(CHECK.SSHCheckError) as caught:
                self.runner.run({}, 2, pulse=lambda: None, cancelled=lambda: False)
            popen.assert_not_called()
        self.assertEqual(caught.exception.code, "SSH_CLEANUP_FAILED")
        self.assertIs(self.runner._process, process)
        process.poll.return_value = 0
        process.wait.side_effect = None

    def test_close_cancels_active_check_and_reaps_it(self):
        active, errors = threading.Event(), []
        def work():
            try:
                self.run_child("import time; time.sleep(30)", pulse=active.set)
            except Exception as exc:
                errors.append(exc)
        supervisor = threading.Thread(target=work)
        supervisor.start()
        self.assertTrue(active.wait(2))
        self.runner.close()
        supervisor.join(2)
        self.assertFalse(supervisor.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], CHECK.SSHCheckCancelled)
        self.assertIsNone(self.runner._process)
        with self.assertRaises(CHECK.SSHCheckCancelled):
            self.runner.run({}, 2, pulse=lambda: None, cancelled=lambda: False)

    def test_no_credentials_in_argv_or_environment(self):
        sentinel = "FAKE-SENSITIVE-CREDENTIAL"
        original = CHECK.subprocess.Popen
        captured = []
        def start(*args, **kwargs):
            captured.append((args, kwargs))
            return original(*args, **kwargs)
        with patch.dict(os.environ, {"SWARM_KEY": sentinel, "PYTHONPATH": sentinel}):
            with patch.object(CHECK.subprocess, "Popen", side_effect=start):
                with self.assertRaises(CHECK.SSHCheckError) as caught:
                    self.runner.run({"password": sentinel}, 5, pulse=lambda: None, cancelled=lambda: False)
        self.assertEqual(caught.exception.code, "SSH_CONFIG_ERROR")
        self.assertNotIn(sentinel, repr(captured))
        self.assertIn("-I", captured[0][0][0])
        self.assertEqual(captured[0][1]["stderr"], subprocess.DEVNULL)
        self.assertEqual(captured[0][1]["stdin"], subprocess.PIPE)

    def test_bad_child_result_fails_closed_without_echoing_output(self):
        for output in (b"secret exception traceback", b"[]", b'{"ok":true}',
                       b'{"ok":false,"error":"secret password"}'):
            with self.subTest(output=output), patch.object(self.runner, "_run_process", return_value=output):
                with self.assertRaises(CHECK.SSHCheckError) as caught:
                    self.runner.run({}, 2, pulse=lambda: None, cancelled=lambda: False)
                self.assertEqual(str(caught.exception), "SSH_WORKER_FAILED")

    def test_invalid_request_is_rejected_before_spawn(self):
        for profile, timeout in (({}, 0), ({}, True), ({}, 301), ({"key": "x" * CHECK.MAX_REQUEST}, 2)):
            with self.subTest(timeout=timeout), patch.object(CHECK.subprocess, "Popen") as popen:
                with self.assertRaises(CHECK.SSHCheckError):
                    self.runner.run(profile, timeout, pulse=lambda: None, cancelled=lambda: False)
                popen.assert_not_called()

    def test_child_crash_and_output_limit_are_reported(self):
        with self.assertRaises(CHECK.SSHCheckError):
            self.run_child("raise RuntimeError('fake sensitive error')")
        with patch.object(CHECK, "MAX_RESPONSE", 8):
            with self.assertRaises(CHECK.SSHCheckError):
                self.run_child("print('x' * 20)")

    def test_launch_failure_releases_slot_for_retry(self):
        with patch.object(CHECK.subprocess, "Popen", side_effect=OSError("sensitive path")):
            with self.assertRaises(CHECK.SSHCheckError) as caught:
                self.runner.run({}, 2, pulse=lambda: None, cancelled=lambda: False)
        self.assertEqual(str(caught.exception), "SSH_WORKER_FAILED")
        self.assertEqual(self.run_child("print('retry')").strip(), b"retry")

    def test_expired_result_is_not_accepted_even_if_child_has_finished(self):
        # Slow supervisor progress cannot turn a late healthy result into success.
        def slow_pulse():
            time.sleep(0.4)
        with self.assertRaises(CHECK.SSHCheckError) as caught:
            self.run_child("import time; time.sleep(0.15); print('late')", timeout=0.05,
                           pulse=slow_pulse)
        self.assertEqual(caught.exception.code, "SSH_TIMEOUT")

    def test_linux_hardening_is_fail_closed_and_checks_parent_race(self):
        import ctypes
        libc = Mock()
        libc.prctl.return_value = 0
        with patch.object(CHECK.sys, "platform", "linux"), \
                patch.object(CHECK.signal, "SIGKILL", 9, create=True), \
                patch.object(ctypes, "CDLL", return_value=libc):
            with patch.object(CHECK.os, "getppid", return_value=123):
                CHECK._protect_child(123)
                self.assertEqual(libc.prctl.call_args_list[0].args, (4, 0, 0, 0, 0))
                self.assertEqual(libc.prctl.call_args_list[1].args, (1, 9, 0, 0, 0))
                with self.assertRaises(RuntimeError):
                    CHECK._protect_child(456)
            libc.prctl.return_value = -1
            with self.assertRaises(RuntimeError):
                CHECK._protect_child(123)

    @unittest.skipIf(SSH is None, "paramiko is not installed")
    def test_connection_error_classification_and_pin_enforcement(self):
        cases = [
            (SSH.HostKeyMismatch("secret"), "SSH_HOST_KEY_MISMATCH"),
            (SSH.paramiko.AuthenticationException("secret"), "SSH_AUTH_FAILED"),
            (socket.timeout("secret"), "SSH_TIMEOUT"),
            (socket.gaierror("secret"), "SSH_DNS_ERROR"),
            (ConnectionRefusedError("secret"), "SSH_CONNECTION_FAILED"),
            (SSH.paramiko.SSHException("secret"), "SSH_PROTOCOL_ERROR"),
            (ValueError("secret"), "SSH_CONFIG_ERROR"),
            (RuntimeError("secret"), "MATRIXD_CHECK_FAILED"),
        ]
        for exc, expected in cases:
            self.assertEqual(CHECK._error_code(exc, SSH), expected)
        key = SSH.paramiko.RSAKey.generate(1024)
        with self.assertRaises(SSH.HostKeyMismatch):
            SSH._PinnedPolicy("SHA256:not-the-real-host-key").missing_host_key(None, "test", key)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux prctl protection")
    def test_linux_child_disables_core_dumps(self):
        script = (
            "import importlib.util, ctypes, os; "
            f"s=importlib.util.spec_from_file_location('check', {str(CHECK.__file__)!r}); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "m._protect_child(os.getppid()); print(ctypes.CDLL(None).prctl(3,0,0,0,0))"
        )
        self.assertEqual(self.run_child(script).strip(), b"0")


@unittest.skipIf(SSH is None, "paramiko is not installed")
class HarvesterLoopbackSSHTests(unittest.TestCase):
    """Real SSH handshake plus the actual isolated checker entry point."""

    def check_server(self, mode):
        key = SSH.paramiko.RSAKey.generate(2048)
        stopped = threading.Event()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        commands = []

        class Server(SSH.paramiko.ServerInterface):
            def check_auth_password(self, username, password):
                return SSH.paramiko.AUTH_FAILED if mode == "auth" else SSH.paramiko.AUTH_SUCCESSFUL

            def get_allowed_auths(self, username):
                return "password"

            def check_channel_request(self, kind, chanid):
                return SSH.paramiko.OPEN_SUCCEEDED

            def check_channel_exec_request(self, channel, command):
                commands.append(command.decode())
                return True

        def serve():
            transport = None
            try:
                conn, _ = listener.accept()
                transport = SSH.paramiko.Transport(conn)
                transport.add_server_key(key)
                transport.start_server(server=Server())
                channel = transport.accept(5)
                if channel is not None:
                    until = time.monotonic() + 5
                    while not commands and time.monotonic() < until and not stopped.wait(0.01):
                        pass
                    if mode == "hang":
                        stopped.wait(5)
                    else:
                        channel.sendall(b'{"version":1,"universes":[]}')
                        channel.send_exit_status(0)
                        channel.close()
            except (OSError, EOFError, SSH.paramiko.SSHException):
                pass
            finally:
                if transport is not None:
                    transport.close()

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        runner = CHECK.SSHCheckRunner()
        pin = "SHA256:" + base64.b64encode(sha256(key.asbytes()).digest()).decode()
        profile = {"host": "127.0.0.1", "port": port, "username": "test", "password": "fake",
                   "auth_type": "password", "trusted_host_fingerprint": pin}
        if mode == "pin":
            profile["trusted_host_fingerprint"] = "SHA256:deliberately-wrong-key"
        try:
            result = runner.run(profile, 2 if mode == "hang" else 5,
                                pulse=lambda: None, cancelled=lambda: False)
            self.assertEqual(json.loads(result), {"version": 1, "universes": []})
            self.assertEqual(commands, [SSH.MATRIXD_LIST_COMMAND])
        finally:
            runner.close()
            stopped.set()
            server.join(6)
            self.assertFalse(server.is_alive())

    def test_real_ssh_snapshot(self):
        self.check_server("healthy")

    def test_real_authentication_failure(self):
        with self.assertRaises(CHECK.SSHCheckError) as caught:
            self.check_server("auth")
        self.assertEqual(caught.exception.code, "SSH_AUTH_FAILED")

    def test_real_host_key_mismatch(self):
        with self.assertRaises(CHECK.SSHCheckError) as caught:
            self.check_server("pin")
        self.assertEqual(caught.exception.code, "SSH_HOST_KEY_MISMATCH")

    def test_real_hanging_command_hits_total_deadline(self):
        with self.assertRaises(CHECK.SSHCheckError) as caught:
            self.check_server("hang")
        self.assertEqual(caught.exception.code, "SSH_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
