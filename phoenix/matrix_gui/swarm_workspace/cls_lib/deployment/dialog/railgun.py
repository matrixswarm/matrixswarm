"""

Commander Edition — Standalone Railgun Module
Non-blocking SSH deploy with full live output streaming.
"""
from matrix_gui.modules.railgun.remote_shell import (
    build_remote_matrixd_command,
    describe_runtime_capabilities,
    describe_universe_teardown_grant,
    mcp_worker_linux_user,
    send_boot_envelope,
    validate_linux_user,
    validate_remote_token,
    verify_remote_matrixd_stdin,
)
from matrix_gui.modules.railgun.ssh_support import connect_ssh_profile

import threading
import time
import hashlib
import json
from PyQt6.QtCore import QThread, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QLabel, QHBoxLayout, QPushButton
)
from PyQt6.QtGui import QMovie


# ============================================================
# QThread Worker — Handles SSH and diskless remote boot
# ============================================================

class RailgunWorker(QThread):
    sig_stdout = pyqtSignal(str)
    sig_stderr = pyqtSignal(str)
    sig_done = pyqtSignal(int)
    sig_error = pyqtSignal(str)

    def __init__(self, ssh_meta, encrypted_bundle, swarm_key_b64, opts):
        super().__init__()
        self.ssh_meta = ssh_meta
        self.encrypted_bundle = encrypted_bundle
        self.swarm_key = swarm_key_b64.strip()
        self.opts = opts
        self._cancel = threading.Event()
        self._remote_started = False
        self._attempt_guard = threading.Lock()
        self.fresh_success = False
        self._receipt_tail = ""

    def _stdout(self, data):
        text = data.decode(errors="replace")
        self._receipt_tail = (self._receipt_tail + text)[-8192:]
        marker = f"[RAILGUN][COMPLETED] request={self.opts.get('railgun_request_id')} exit=0"
        if marker + "\n" in self._receipt_tail or marker + "\r\n" in self._receipt_tail:
            self.fresh_success = True
        self.sig_stdout.emit(text)

    def cancel(self):
        self._cancel.set()

    def _check_cancel(self):
        if self._cancel.is_set():
            raise InterruptedError("Local deployment cancelled")

    def run(self):
        # A worker represents one attempt. Reusing it must never replay a boot
        # after a lost acknowledgement (even if QThread.start is called again).
        if not self._attempt_guard.acquire(blocking=False):
            self.sig_error.emit(
                "This deployment attempt has already run. Check the target "
                "universe before starting a new attempt."
            )
            return
        client = None
        chan = None
        try:
            self._check_cancel()
            # Reject malformed command data before opening SSH.
            universe = validate_remote_token(
                self.opts["universe"],
                "Universe name",
            )
            linux_user = validate_linux_user(
                self.opts["linux_user"], "Swarm Linux user"
            )
            reboot_id = None
            if self.opts.get("reboot_id"):
                reboot_id = validate_remote_token(
                    self.opts["reboot_id"],
                    "Reboot ID",
                )

            # 1. SSH Connect with the Registry's pinned host identity.
            client, actual_fingerprint = connect_ssh_profile(self.ssh_meta)
            self._check_cancel()
            self.sig_stdout.emit(
                f"[RAILGUN] Host fingerprint verified: "
                f"{actual_fingerprint}\n"
            )
            verify_remote_matrixd_stdin(client)
            self._check_cancel()
            self.sig_stdout.emit(
                "[RAILGUN] Remote MatrixD sealed-stream capability verified.\n"
            )

            # 2. Build boot command. Detached agents must never inherit this
            # SSH channel, so --verbose is deliberately suppressed here.
            flags = []
            for flag in [
                "debug", "clean", "reboot", "rug_pull", "reboot_new",
                "protect_memory",
            ]:
                if self.opts.get(flag):
                    flags.append("--" + flag.replace("_", "-"))

            if self.opts.get("verbose"):
                self.sig_stdout.emit(
                    "[RAILGUN][INFO] --verbose suppressed for detached SSH boot; "
                    "use cockpit agent logs for live output.\n"
                )

            runtime_capabilities = self.opts.get("runtime_capabilities") or {}
            cmd = build_remote_matrixd_command(
                action="start",
                universe=universe,
                linux_user=linux_user,
                boot_flags=flags,
                reboot_id=reboot_id,
                runtime_capabilities=runtime_capabilities,
                request_id=self.opts.get("railgun_request_id") or hashlib.sha256(
                    json.dumps({"bundle": self.encrypted_bundle, "universe": universe,
                        "user": linux_user, "flags": flags, "reboot_id": reboot_id,
                        "capabilities": runtime_capabilities}, sort_keys=True).encode()
                ).hexdigest(),
            )
            self.sig_stdout.emit(
                f"[RAILGUN] Universe account: {linux_user}\n"
            )
            if self.opts.get("protect_memory"):
                self.sig_stdout.emit(
                    "[RAILGUN] Agent memory boundary: root-only inspection "
                    "requested.\n"
                )
            grants = describe_runtime_capabilities(runtime_capabilities)
            grants.append(describe_universe_teardown_grant(universe))
            self.sig_stdout.emit(
                f"[RAILGUN] Railgun-managed active grants: {len(grants)}\n"
            )
            for grant in grants:
                self.sig_stdout.emit(f"[RAILGUN]   {grant}\n")
            if not grants:
                self.sig_stdout.emit(
                    "[RAILGUN]   none — unprivileged universe account\n"
                )
            if runtime_capabilities.get("mcp_worker"):
                self.sig_stdout.emit(
                    "[RAILGUN] MCP worker account: "
                    f"{mcp_worker_linux_user(linux_user)} (isolated)\n"
                )
            self.sig_stdout.emit(
                "[RAILGUN] Root provisioning prepared; sealed boot payload "
                "will travel only over SSH stdin.\n"
            )

            # 3. This is a non-interactive background deployment. Do not
            # allocate a PTY: matrixd's detached children must not retain it.
            transport = client.get_transport()
            chan = transport.open_session(timeout=15)
            chan.settimeout(1)
            self._check_cancel()
            # Once command dispatch begins, cancellation cannot certify rollback.
            self._remote_started = True
            chan.exec_command(cmd)
            payload_size = send_boot_envelope(
                chan, self.encrypted_bundle, self.swarm_key,
                check_cancel=self._check_cancel,
            )
            self.sig_stdout.emit(
                f"[RAILGUN] Streamed sealed boot envelope "
                f"({payload_size} bytes); no remote directive/key file created.\n"
            )

            deadline = time.monotonic() + 120
            while True:
                self._check_cancel()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Remote boot response timed out")
                while chan.recv_ready():
                    self._check_cancel()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Remote boot response timed out")
                    self._stdout(chan.recv(4096))
                while chan.recv_stderr_ready():
                    self._check_cancel()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Remote boot response timed out")
                    self.sig_stderr.emit(chan.recv_stderr(4096).decode(errors="ignore"))
                if chan.exit_status_ready():
                    break
                self.msleep(60)

            # Drain anything delivered with the exit status.
            while chan.recv_ready():
                self._check_cancel()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Remote boot response timed out")
                self._stdout(chan.recv(4096))
            while chan.recv_stderr_ready():
                self._check_cancel()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Remote boot response timed out")
                self.sig_stderr.emit(chan.recv_stderr(4096).decode(errors="ignore"))

            exit_code = chan.recv_exit_status()
            if exit_code < 0:
                raise ConnectionError("SSH closed without a remote exit status")
            self.sig_done.emit(exit_code)

        except Exception as e:
            from matrix_gui.util.exception_diagnostics import log_exception_locations
            log_exception_locations("Railgun deployment", e)
            outcome = (
                "Remote outcome unknown. Check the target universe before retrying; "
                "stopping this connection does not stop a remote deployment."
                if self._remote_started else "No remote boot command was dispatched."
            )
            self.sig_error.emit(f"Local operation stopped ({type(e).__name__}). {outcome}")
        finally:
            if chan is not None:
                try:
                    chan.close()
                except Exception:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


# ============================================================
# UI Dialog — Smooth, Non-blocking, Phoenix Ready
# ============================================================

class RailgunDialog(QDialog):

    @staticmethod
    def launch(parent, ssh_meta, encrypted_bundle, swarm_key_b64, opts):
        dlg = RailgunDialog(
            parent, ssh_meta, encrypted_bundle, swarm_key_b64, opts
        )
        dlg.show()

    def __init__(self, parent, ssh_meta, encrypted_bundle, swarm_key_b64, opts):
        super().__init__(parent)

        self.setWindowTitle(f"Railgun Deploy: {ssh_meta.get('host')}")
        self.resize(900, 540)
        self._success_cleanup = opts.get("success_cleanup")

        layout = QVBoxLayout(self)

        # --- Spinner Row ---
        top = QHBoxLayout()
        self.spinner_label = QLabel()
        self.spinner = QMovie("matrix_gui/theme/spinner.gif")
        self.spinner.setScaledSize(QSize(32, 32))
        self.spinner_label.setMovie(self.spinner)
        self.spinner.start()
        top.addWidget(self.spinner_label)

        self.status_label = QLabel("[RAILGUN]  🔴  LIVE DEPLOY STREAM  🔴")
        self.status_label.setStyleSheet("color:#00ff00; font-weight:bold;")
        top.addWidget(self.status_label)
        top.addStretch(1)

        layout.addLayout(top)

        # --- Output Console ---
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet(
            "background:#000; color:#00ff00; font-family: Consolas; font-size:13px;"
        )
        layout.addWidget(self.console)

        # --- Worker Setup ---
        self.worker = RailgunWorker(
            ssh_meta, encrypted_bundle, swarm_key_b64, opts
        )
        self.worker.setParent(self)
        self.cancel_button = QPushButton("Cancel local operation")
        self.cancel_button.clicked.connect(self._request_cancel)
        layout.addWidget(self.cancel_button)
        self.worker.finished.connect(lambda: self.cancel_button.setEnabled(False))

        # Connect signals → UI
        self.worker.sig_stdout.connect(self.append_stdout)
        self.worker.sig_stderr.connect(self.append_stderr)
        self.worker.sig_done.connect(self.finish)
        self.worker.sig_error.connect(self.fail)

        # Launch deploy thread
        self.worker.start()

    def _request_cancel(self):
        self.worker.cancel()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Stopping local operation; waiting for SSH cleanup…")

    def _can_close(self):
        if self.worker.isRunning():
            self._request_cancel()
            return False
        return True

    def reject(self):
        if self._can_close():
            super().reject()

    def done(self, result):
        if self._can_close():
            super().done(result)

    def closeEvent(self, event):
        if self._can_close():
            event.accept()
        else:
            event.ignore()

    # ========================================================
    # GUI Event Handlers
    # ========================================================

    def append_stdout(self, text):
        self.console.append(text)

    def append_stderr(self, text):
        self.console.append(f"<span style='color:red;'>{text}</span>")

    def finish(self, code):
        self.status_label.setText(f"Remote command finished (exit={code})")
        self.spinner.stop()
        self.spinner_label.hide()
        self.console.append(f"\n[RAILGUN] Deploy finished (exit={code})")
        if self._success_cleanup and code == 0:
            if self.worker.fresh_success and not self.worker._cancel.is_set():
                cleanup, self._success_cleanup = self._success_cleanup, None
                try:
                    count = cleanup()
                    self.console.append(f"[CLEANUP] Removed {count} previous matching deployment record(s) from the vault; server files unchanged.")
                except Exception as error:
                    from matrix_gui.util.exception_diagnostics import log_exception_locations
                    log_exception_locations("Deployment record cleanup", error)
                    self.console.append("[CLEANUP WARNING] Deployment finished, but vault cleanup failed. Previous records retained; inspect the diagnostic log.")
            else:
                self.console.append("[CLEANUP] Previous records retained: no fresh successful completion receipt (update MatrixOS helper if needed).")

    def fail(self, error):
        self.status_label.setText(error)
        self.spinner.stop()
        self.spinner_label.hide()
        self.console.append(f"<span style='color:red;'>[ERROR] {error}</span>")
