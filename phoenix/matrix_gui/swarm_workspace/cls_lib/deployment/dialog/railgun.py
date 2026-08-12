"""

Commander Edition — Standalone Railgun Module
Non-blocking SSH deploy with full live output streaming.
"""
import io
import ntpath
import posixpath
import paramiko

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
        try:
            host = self.ssh_meta["host"]
            user = self.ssh_meta["username"]
            port = int(self.ssh_meta.get("port", 22))

            # 1. SSH Connect
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            auth_type = self.ssh_meta.get("auth_type", "private_key")

            if auth_type == "password":
                client.connect(
                    host,
                    port=port,
                    username=user,
                    password=self.ssh_meta.get("password"),
                    look_for_keys=False,
                    allow_agent=False
                )

            elif auth_type == "private_key":
                key_text = self.ssh_meta.get("private_key")
                privkey = paramiko.RSAKey.from_private_key(io.StringIO(key_text))

                client.connect(
                    host,
                    port=port,
                    username=user,
                    pkey=privkey,
                    look_for_keys=False,
                    allow_agent=False
                )

            elif auth_type == "agent":
                client.connect(
                    host,
                    port=port,
                    username=user,
                    allow_agent=True
                )

            # 2. Upload directive
            sftp = client.open_sftp()
            remote_root = "/matrix/boot_directives"

            try:
                sftp.stat(remote_root)
            except FileNotFoundError:
                sftp.mkdir(remote_root)

            remote_bundle = posixpath.join(remote_root, ntpath.basename(self.local_bundle))
            sftp.put(self.local_bundle, remote_bundle)
            sftp.close()

            # 3. Build boot command
            universe = self.opts["universe"]

            flags = []
            for f in ["verbose", "debug", "clean", "reboot", "rug_pull", "reboot_new"]:
                if self.opts.get(f):
                    flags.append("--" + f.replace("_", "-"))

            if self.opts.get("reboot_id"):
                flags.append(f"--reboot-id {self.opts['reboot_id']}")

            boot_flags = " ".join(flags)

            cmd = (
                f"cd /matrix && "
                f"export SITE_ROOT=/matrix && "
                f"export SWARM_KEY='{self.swarm_key}' && "
                f"[ -d /matrix/venv ] && source /matrix/venv/bin/activate || true && "
                f"(matrixd boot --universe {universe} --directive {remote_bundle} {boot_flags}) "
                f"2>&1"
            )

            # 4. Execute command and stream output
            transport = client.get_transport()
            chan = transport.open_session()
            chan.get_pty()
            chan.exec_command(cmd)

            while True:
                if chan.recv_ready():
                    self.sig_stdout.emit(chan.recv(4096).decode(errors="ignore"))
                if chan.recv_stderr_ready():
                    self.sig_stderr.emit(chan.recv_stderr(4096).decode(errors="ignore"))
                if chan.exit_status_ready():
                    break
                self.msleep(60)

            code = chan.recv_exit_status()
            self.sig_done.emit(code)
            client.close()

        except Exception as e:
            self.sig_error.emit(str(e))



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
