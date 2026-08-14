"""

Commander Edition — Standalone Railgun Module
Non-blocking SSH deploy with full live output streaming.
"""
import ntpath
import posixpath
from matrix_gui.modules.railgun.remote_shell import (
    quote_remote_argument,
    validate_remote_token,
)
from matrix_gui.modules.railgun.ssh_support import connect_ssh_profile

from PyQt6.QtCore import QThread, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QLabel, QHBoxLayout
)
from PyQt6.QtGui import QMovie


# ============================================================
# QThread Worker — Handles SSH, SFTP, and remote boot
# ============================================================

class RailgunWorker(QThread):
    sig_stdout = pyqtSignal(str)
    sig_stderr = pyqtSignal(str)
    sig_done = pyqtSignal(int)
    sig_error = pyqtSignal(str)

    def __init__(self, ssh_meta, local_bundle, swarm_key_b64, opts):
        super().__init__()
        self.ssh_meta = ssh_meta
        self.local_bundle = local_bundle
        self.swarm_key = swarm_key_b64.strip()
        self.opts = opts

    def run(self):
        client = None
        chan = None
        try:
            # Reject malformed command data before opening SSH or uploading.
            universe = validate_remote_token(
                self.opts["universe"],
                "Universe name",
            )
            bundle_name = validate_remote_token(
                ntpath.basename(self.local_bundle),
                "Directive filename",
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

            # 2. Upload directive
            sftp = client.open_sftp()
            remote_root = "/matrix/boot_directives"

            try:
                sftp.stat(remote_root)
            except FileNotFoundError:
                sftp.mkdir(remote_root)

            remote_bundle = posixpath.join(remote_root, bundle_name)
            sftp.put(self.local_bundle, remote_bundle)
            sftp.close()

            # 3. Build boot command. Detached agents must never inherit this
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

            if reboot_id:
                flags.extend(
                    ["--reboot-id", quote_remote_argument(reboot_id, "Reboot ID")]
                )

            boot_flags = " ".join(flags)
            quoted_universe = quote_remote_argument(universe, "Universe name")
            quoted_bundle = quote_remote_argument(remote_bundle, "Directive path")
            quoted_swarm_key = quote_remote_argument(self.swarm_key, "SWARM_KEY")

            cmd = (
                f"cd /matrix && "
                f"export SITE_ROOT=/matrix && "
                f"export SWARM_KEY={quoted_swarm_key} && "
                f"if [ -f /matrix/.venv/bin/activate ]; then . /matrix/.venv/bin/activate; fi && "
                f"(matrixd boot --universe {quoted_universe} "
                f"--directive {quoted_bundle} {boot_flags}) "
                f"2>&1"
            )

            # 4. This is a non-interactive background deployment. Do not
            # allocate a PTY: matrixd's detached children must not retain it.
            transport = client.get_transport()
            chan = transport.open_session()
            chan.exec_command(cmd)

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
    def launch(parent, ssh_meta, local_bundle, swarm_key_b64, opts):
        dlg = RailgunDialog(parent, ssh_meta, local_bundle, swarm_key_b64, opts)
        dlg.show()

    def __init__(self, parent, ssh_meta, local_bundle, swarm_key_b64, opts):
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
        self.worker = RailgunWorker(ssh_meta, local_bundle, swarm_key_b64, opts)

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
