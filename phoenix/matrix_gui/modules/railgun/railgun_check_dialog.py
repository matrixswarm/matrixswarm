# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition — Railgun Remote Host Recon
import io
import paramiko
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QTextEdit, QMessageBox
)
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton

class RailgunCheckDialog(QDialog):
    """
    Remote system reconnaissance for MatrixOS deployment.
    Checks:
        - SSH connectivity
        - OS type (Ubuntu/CentOS/Rocky)
        - Python3 presence
        - pip / venv availability
        - /matrix existence
        - Disk space
        - System clock
        - Existing MatrixOS installation
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("⚡ Railgun — Check Remote Host")
        self.resize(720, 520)

        layout = QVBoxLayout(self)

        # =======================
        # SSH TARGET
        # =======================
        ssh_box = QHBoxLayout()
        ssh_box.addWidget(QLabel("<b>SSH Target:</b>"))

        self.ssh_selector = QComboBox()
        vault = self._vault()

        ssh_map = vault.get("connection_manager", {}).get("ssh", {})

        for sid, meta in ssh_map.items():
            label = meta.get("label", sid)
            self.ssh_selector.addItem(f"{label} ({meta.get('host')})", meta)

        ssh_box.addWidget(self.ssh_selector)
        layout.addLayout(ssh_box)

        # =======================
        # ACTION BUTTONS
        # =======================
        btn_box = QGridLayout()

        self.btn_run_all = QPushButton("Run Full Check")
        self.btn_run_all.clicked.connect(self._run_all)
        btn_box.addWidget(self.btn_run_all, 0, 0, 1, 2)

        self.btn_check_ssh = QPushButton("Check SSH")
        self.btn_check_ssh.clicked.connect(self.check_ssh)
        btn_box.addWidget(self.btn_check_ssh, 1, 0)

        self.btn_check_os = QPushButton("Check OS")
        self.btn_check_os.clicked.connect(self.check_os)
        btn_box.addWidget(self.btn_check_os, 1, 1)

        self.btn_check_python = QPushButton("Check Python")
        self.btn_check_python.clicked.connect(self.check_python)
        btn_box.addWidget(self.btn_check_python, 2, 0)

        self.btn_check_matrix_path = QPushButton("Check /matrix Path")
        self.btn_check_matrix_path.clicked.connect(self.check_matrix_path)
        btn_box.addWidget(self.btn_check_matrix_path, 2, 1)

        self.btn_disk = QPushButton("Check Disk Space")
        self.btn_disk.clicked.connect(self.check_disk)
        btn_box.addWidget(self.btn_disk, 3, 0)

        self.btn_clock = QPushButton("Check System Clock")
        self.btn_clock.clicked.connect(self.check_clock)
        btn_box.addWidget(self.btn_clock, 3, 1)

        self.btn_existing = QPushButton("Check Existing MatrixOS")
        self.btn_existing.clicked.connect(self.check_existing)
        btn_box.addWidget(self.btn_existing, 4, 0, 1, 2)

        layout.addLayout(btn_box)

        # =======================
        # OUTPUT TERMINAL
        # =======================
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setStyleSheet(
            "background:#000; color:#0f0; font-family:Consolas,monospace; font-size:12px;"
        )
        layout.addWidget(self.output_box)

        # SSH client
        self.client = None

    # -----------------------------------------------------
    # SSH INIT
    # -----------------------------------------------------
    def _vault(self):
        """Always fetch the live vault snapshot."""
        return VaultCoreSingleton.get().read()

    def refresh_targets(self):
        self.ssh_selector.clear()
        vault = self._vault()
        ssh_map = vault.get("connection_manager", {}).get("ssh", {})

        for sid, meta in ssh_map.items():
            label = meta.get("label", sid)
            self.ssh_selector.addItem(f"{label} ({meta.get('host')})", meta)

    def _connect(self):
        ssh_cfg = self.ssh_selector.currentData()
        if not ssh_cfg:
            QMessageBox.critical(self, "No SSH Target", "No SSH target found in vault.")
            return None

        try:
            host = ssh_cfg.get("host")
            user = ssh_cfg.get("username")
            port = int(ssh_cfg.get("port", 22))
            privkey_pem = ssh_cfg.get("private_key")

            key = paramiko.RSAKey.from_private_key(io.StringIO(privkey_pem))

            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(host, port=port, username=user, pkey=key)

            return self.client

        except Exception as e:
            emit_gui_exception_log("RailgunCheck.connect", e)
            self.output_box.append(f"<span style='color:red'>[SSH ERROR] {e}</span>")
            return None

    def _run(self, cmd):
        """Runs a command and streams output."""
        try:
            if not self.client:
                self.client = self._connect()
                if not self.client:
                    return ""

            stdin, stdout, stderr = self.client.exec_command(cmd)

            out = stdout.read().decode(errors="ignore")
            err = stderr.read().decode(errors="ignore")

            if out.strip():
                self.output_box.append(out)
            if err.strip():
                self.output_box.append(f"<span style='color:red'>{err}</span>")

            return out.strip()

        except Exception as e:
            emit_gui_exception_log("RailgunCheck.run", e)
            self.output_box.append(f"<span style='color:red'>[RUN ERROR] {e}</span>")
            return ""

    # -----------------------------------------------------
    # CHECKS
    # -----------------------------------------------------
    def check_ssh(self):
        self.output_box.append("[Check] Testing SSH connectivity…")
        if self._connect():
            self.output_box.append("[OK] SSH connection established.")
        else:
            self.output_box.append("<span style='color:red'>[FAIL] SSH failed.</span>")

    def check_os(self):
        self.output_box.append("[Check] Detecting OS…")
        cmd = "cat /etc/os-release"
        resp = self._run(cmd)
        if "Ubuntu" in resp or "Debian" in resp:
            self.output_box.append("[OK] OS: Debian/Ubuntu family")
        elif "CentOS" in resp or "Rocky" in resp or "Red Hat" in resp:
            self.output_box.append("[OK] OS: RHEL/CentOS/Rocky family")
        else:
            self.output_box.append("<span style='color:yellow'>[WARN] Unknown OS type</span>")

    def check_python(self):
        self.output_box.append("[Check] Looking for Python3…")
        resp = self._run("which python3 || true")
        if resp:
            self.output_box.append(f"[OK] Found Python3 at {resp}")
        else:
            self.output_box.append("<span style='color:red'>[FAIL] Python3 not found.</span>")

        self.output_box.append("[Check] Checking pip…")
        resp = self._run("which pip3 || true")
        if resp:
            self.output_box.append(f"[OK] Found pip at {resp}")
        else:
            self.output_box.append("<span style='color:red'>[FAIL] pip3 not found.</span>")

        self.output_box.append("[Check] Checking venv…")
        resp = self._run("python3 -m venv --help >/dev/null 2>&1 && echo OK || echo FAIL")
        if "OK" in resp:
            self.output_box.append("[OK] venv available")
        else:
            self.output_box.append("<span style='color:red'>[FAIL] venv module missing</span>")

    def check_matrix_path(self):
        self.output_box.append("[Check] Checking /matrix directory…")
        resp = self._run("[ -d /matrix ] && echo EXISTS || echo NO")
        if "EXISTS" in resp:
            self.output_box.append("[OK] /matrix exists")
        else:
            self.output_box.append("[INFO] /matrix missing (will be created by installer)")

    def check_disk(self):
        self.output_box.append("[Check] Checking disk space…")
        resp = self._run("df -h / | tail -1 | awk '{print $4}'")
        self.output_box.append(f"[OK] Free space: {resp}")

    def check_clock(self):
        self.output_box.append("[Check] Checking system clock…")
        resp = self._run("date")
        self.output_box.append(f"[OK] System time: {resp}")

    def check_existing(self):
        self.output_box.append("[Check] Looking for existing MatrixOS install…")
        resp = self._run("[ -f /matrix/matrixd ] && echo YES || echo NO")
        if "YES" in resp:
            self.output_box.append("<span style='color:yellow'>[WARN] MatrixOS already installed.</span>")
        else:
            self.output_box.append("[OK] No existing MatrixOS detected.")

    # -----------------------------------------------------
    # RUN ALL
    # -----------------------------------------------------
    def _run_all(self):
        self.refresh_targets()
        self.output_box.append("\n⚡ <b>Running Full Recon...</b>\n")
        self.check_ssh()
        self.check_os()
        self.check_python()
        self.check_matrix_path()
        self.check_disk()
        self.check_clock()
        self.check_existing()
        self.output_box.append("\n⚡ <b>Recon Complete.</b>\n")
