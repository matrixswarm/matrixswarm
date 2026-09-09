"""

Commander Edition — Standalone Railgun Module
Non-blocking SSH deploy with full live output streaming.
"""
from matrix_gui.modules.railgun.remote_shell import (
    build_remote_matrixd_command,
    describe_runtime_capabilities,
    mcp_worker_linux_user,
    send_boot_envelope,
    validate_linux_user,
    validate_remote_token,
    verify_remote_matrixd_stdin,
)
from matrix_gui.modules.railgun.ssh_support import connect_ssh_profile

from PyQt6.QtCore import QThread, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QLabel, QHBoxLayout
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

    def run(self):
        client = None
        chan = None
        try:
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
            self.sig_stdout.emit(
                f"[RAILGUN] Host fingerprint verified: "
                f"{actual_fingerprint}\n"
            )
            verify_remote_matrixd_stdin(client)
            self.sig_stdout.emit(
                "[RAILGUN] Remote MatrixD sealed-stream capability verified.\n"
            )

            # 2. Build boot command. Detached agents must never inherit this
            # SSH channel, so --verbose is deliberately suppressed here.
            flags = []
            for flag in ["debug", "clean", "reboot", "rug_pull", "reboot_new"]:
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
            )
            self.sig_stdout.emit(
                f"[RAILGUN] Universe account: {linux_user}\n"
            )
            grants = describe_runtime_capabilities(runtime_capabilities)
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
            chan = transport.open_session()
            chan.exec_command(cmd)
            payload_size = send_boot_envelope(
                chan, self.encrypted_bundle, self.swarm_key
            )
            self.sig_stdout.emit(
                f"[RAILGUN] Streamed sealed boot envelope "
                f"({payload_size} bytes); no remote directive/key file created.\n"
            )

            while True:
                while chan.recv_ready():
                    self.sig_stdout.emit(chan.recv(4096).decode(errors="ignore"))
                while chan.recv_stderr_ready():
                    self.sig_stderr.emit(chan.recv_stderr(4096).decode(errors="ignore"))
                if chan.exit_status_ready():
                    break
                self.msleep(60)

            # Drain anything delivered with the exit status.
            while chan.recv_ready():
                self.sig_stdout.emit(chan.recv(4096).decode(errors="ignore"))
            while chan.recv_stderr_ready():
                self.sig_stderr.emit(chan.recv_stderr(4096).decode(errors="ignore"))

            self.sig_done.emit(chan.recv_exit_status())

        except Exception as e:
            self.sig_error.emit(str(e))
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

        # Connect signals → UI
        self.worker.sig_stdout.connect(self.append_stdout)
        self.worker.sig_stderr.connect(self.append_stderr)
        self.worker.sig_done.connect(self.finish)
        self.worker.sig_error.connect(self.fail)

        # Launch deploy thread
        self.worker.start()

    # ========================================================
    # GUI Event Handlers
    # ========================================================

    def append_stdout(self, text):
        self.console.append(text)

    def append_stderr(self, text):
        self.console.append(f"<span style='color:red;'>{text}</span>")

    def finish(self, code):
        self.spinner.stop()
        self.spinner_label.hide()
        self.console.append(f"\n[RAILGUN] Deploy finished (exit={code})")

    def fail(self, error):
        self.spinner.stop()
        self.spinner_label.hide()
        self.console.append(f"<span style='color:red;'>[ERROR] {error}</span>")
