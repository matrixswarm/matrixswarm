# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition — Railgun MatrixOS Installer (Operational Core)
import os
import io
import time
import paramiko
from PyQt6 import QtWidgets
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QTextEdit, QLineEdit, QGroupBox
)
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton

class RailgunInstallDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ssh_map = {}
        self.install_modes = [
            "Install from GitHub",
            "Local Full Install"
        ]
        self.tail_thread = None
        self._build_ui()
        self._extract_ssh_targets()
        self.ssh_map = {}
        self.install_modes = [
            "Install from GitHub",
            "Local Full Install"
        ]
        self.tail_thread = None
        self._build_ui()
        self._extract_ssh_targets()

    def _build_ui(self):
        self.setWindowTitle("⚡ Railgun 2.0 – Commander Edition Installer")
        self.resize(780, 620)
        layout = QVBoxLayout(self)

        # INSTALL MODE
        mode_box = QGroupBox("Install Mode")
        mode_layout = QHBoxLayout(mode_box)
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(self.install_modes)
        mode_layout.addWidget(QLabel("Select Mode:"))
        mode_layout.addWidget(self.mode_selector)
        layout.addWidget(mode_box)

        # PYTHON MODE
        python_box = QGroupBox("Python Environment")
        python_layout = QHBoxLayout(python_box)
        self.python_mode = QComboBox()
        self.python_mode.addItems([
            "Create new venv",
            #"Activate existing venv",
            "Skip Python setup"
        ])
        python_layout.addWidget(QLabel("Python Mode:"))
        python_layout.addWidget(self.python_mode)
        layout.addWidget(python_box)

        # LOCAL PATH
        local_box = QGroupBox("Local Source Path")
        local_layout = QHBoxLayout(local_box)
        self.local_path = QLineEdit()
        self.local_path.setPlaceholderText("Select MatrixOS root folder…")
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_local)
        local_layout.addWidget(self.local_path)
        local_layout.addWidget(browse_btn)
        layout.addWidget(local_box)

        # SSH TARGET
        ssh_box = QGroupBox("SSH Target")
        ssh_layout = QHBoxLayout(ssh_box)
        self.ssh_selector = QComboBox()
        ssh_layout.addWidget(QLabel("Deploy To:"))
        ssh_layout.addWidget(self.ssh_selector)
        layout.addWidget(ssh_box)

        # ACTION BUTTONS
        btn_layout = QHBoxLayout()
        self.btn_install = QPushButton("⚡ Install MatrixOS")
        self.btn_install.clicked.connect(self.run_installer)
        btn_layout.addWidget(self.btn_install)
        layout.addLayout(btn_layout)

        # OUTPUT TERMINAL
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setStyleSheet(
            "background:#000; color:#0f0; font-family:Consolas,monospace; font-size:12px;"
        )
        layout.addWidget(self.output_box)

        self.output_box.append("[Railgun] Installer UI ready.")

    def _vault(self):
        """Fetch the live vault snapshot."""
        return VaultCoreSingleton.get().read()

    def _browse_local(self):
        folder = QFileDialog.getExistingDirectory(self, "Select MatrixOS Root Folder")
        if folder:
            self.local_path.setText(folder)

    def _extract_ssh_targets(self):
        self.ssh_selector.clear()
        vault = self._vault()
        ssh_mgr = vault.get("connection_manager", {}).get("ssh", {})
        self.ssh_map = {}

        if not ssh_mgr:
            self.ssh_selector.addItem("No SSH profiles in vault")
            self.output_box.append("[Railgun] No SSH profiles found in vault.")
            return

        for sid, meta in ssh_mgr.items():
            label = meta.get("label", sid)
            host = meta.get("host")
            user = meta.get("username", "root")
            port = int(meta.get("port", 22))
            key = meta.get("private_key", "")

            self.ssh_selector.addItem(f"{label} ({host})", sid)
            self.ssh_map[sid] = {
                "host": host,
                "username": user,
                "port": port,
                "private_key": key,
            }

        self.output_box.append(f"[Railgun] Loaded {len(self.ssh_map)} SSH profiles.")

    def _get_selected_ssh(self):
        sid = self.ssh_selector.currentData()
        if not sid:
            return None
        return self.ssh_map.get(sid)

    def run_installer(self):
        try:
            self._extract_ssh_targets()  # always refresh SSH targets
            self.output_box.append("[Railgun] Starting installation…")
            ssh_cfg = self._get_selected_ssh()
            if not ssh_cfg:
                self.output_box.append("[Railgun] No valid SSH target.")
                return

            host = ssh_cfg["host"]
            user = ssh_cfg["username"]
            port = ssh_cfg["port"]
            key_pem = ssh_cfg["private_key"]

            if not host or not key_pem:
                self.output_box.append("[Railgun] SSH profile missing host or private key.")
                return

            client = self._connect_ssh(host, user, port, key_pem)
            if not client:
                self.output_box.append("[Railgun] SSH connection failed.")
                return

            remote_staging = self._create_remote_staging(client)

            mode = self.mode_selector.currentText()

            # ----------------------
            # GITHUB INSTALL MODE
            # ----------------------
            if mode == "Install from GitHub":
                self.output_box.append("[Railgun] GitHub mode selected — skipping local upload.")
            else:
                # Must have a local path for Local Full Install
                local_src = self.local_path.text().strip()
                if not local_src:
                    self.output_box.append("[Railgun] No local source selected.")
                    client.close()
                    return

                if not os.path.isdir(local_src):
                    self.output_box.append(f"[Railgun] Local path is not a directory: {local_src}")
                    client.close()
                    return

                sftp = client.open_sftp()
                self._upload_directory(sftp, local_src, remote_staging)
                sftp.close()

            mode = self.mode_selector.currentText()
            python_mode = self.python_mode.currentText()
            pyflag = "create" if python_mode == "Create new venv" else "skip"

            if mode == "Install from GitHub":
                installer_script = self._generate_github_installer(pyflag)
            else:
                installer_script = self._generate_installer(remote_staging, mode, pyflag)

            remote_script = f"{remote_staging}/install_matrixos.sh"
            sftp = client.open_sftp()
            with sftp.file(remote_script, "w") as f:
                f.write(installer_script)
            sftp.chmod(remote_script, 0o755)
            sftp.close()
            self.output_box.append(f"[Railgun] Installer uploaded: {remote_script}")

            cmd = f"PYTHON_MODE={pyflag} bash {remote_script}"
            transport = client.get_transport()
            channel = transport.open_session()
            channel.get_pty()
            channel.exec_command(cmd)

            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode(errors="ignore")
                    self.output_box.append(chunk)
                    QtWidgets.QApplication.processEvents()
                if channel.recv_stderr_ready():
                    err = channel.recv_stderr(4096).decode(errors="ignore")
                    self.output_box.append(f"[ERROR] {err}")
                    QtWidgets.QApplication.processEvents()
                if channel.exit_status_ready():
                    break

            exit_code = channel.recv_exit_status()
            self.output_box.append(f"[Railgun] Installer exited (code={exit_code})")
            client.close()

        except Exception as e:
            self.output_box.append(f"[Railgun ERROR] {e}")

    def _connect_ssh(self, host, user, port, key_pem):
        try:
            key = paramiko.RSAKey.from_private_key(io.StringIO(key_pem))
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=port, username=user, pkey=key)
            self.output_box.append(f"[SSH] Connected to {host}")
            return client
        except Exception as e:
            self.output_box.append(f"[SSH ERROR] {e}")
            return None

    def _create_remote_staging(self, client):
        ts = time.strftime("%Y%m%d_%H%M%S")
        remote = f"/tmp/matrix_staging_{ts}"
        client.exec_command(f"mkdir -p {remote}")
        time.sleep(0.2)  # give remote FS time to settle

        stdin, stdout, stderr = client.exec_command(f"test -d {remote} && echo OK || echo FAIL")
        result = stdout.read().decode().strip()

        if result != "OK":
            self.output_box.append(f"[Railgun ERROR] Failed to create remote staging at {remote}")
        else:
            self.output_box.append(f"[Railgun] Remote staging created: {remote}")

        return remote

    def _upload_directory(self, sftp, local_dir, remote_dir):
        """
        Recursively upload only the MatrixOS runtime directories and files.

        Keeps structure identical to local source:
            agents/, core/, scripts/, boot_directives/, maxmind/
        Includes file types: .py, .txt, .json, .env, .md, .sh, .cfg, .conf
        """
        ALLOWED_DIRS = {"agents", "core", "scripts", "boot_directives", "maxmind"}
        ALLOWED_FILE_EXTS = (".py", ".txt", ".json", ".env", ".md", ".sh", ".cfg", ".conf")

        # Make sure base remote directory exists
        try:
            sftp.listdir(remote_dir)
        except IOError:
            sftp.mkdir(remote_dir)

        for entry in os.listdir(local_dir):
            local_path = os.path.join(local_dir, entry)
            remote_path = f"{remote_dir}/{entry}"

            # ---- DIRECTORY ----
            if os.path.isdir(local_path):

                # skip unwanted directories
                if os.path.abspath(local_dir) == os.path.abspath(self.local_path.text().strip()) and entry not in ALLOWED_DIRS:
                    continue

                # scripts: flat copy (no recursion)
                if entry == "scripts":
                    try:
                        sftp.listdir(remote_path)
                    except IOError:
                        sftp.mkdir(remote_path)

                    for fname in os.listdir(local_path):
                        fp = os.path.join(local_path, fname)
                        rp = f"{remote_path}/{fname}"
                        if os.path.isfile(fp):
                            sftp.put(fp, rp)
                    continue

                # boot_directives: copy only top-level files, not children
                if entry == "boot_directives":
                    try:
                        sftp.listdir(remote_path)
                    except IOError:
                        sftp.mkdir(remote_path)

                    for fname in os.listdir(local_path):
                        fp = os.path.join(local_path, fname)
                        rp = f"{remote_path}/{fname}"
                        if os.path.isfile(fp):
                            sftp.put(fp, rp)
                    continue

                # all other dirs recurse normally
                try:
                    sftp.listdir(remote_path)
                except IOError:
                    sftp.mkdir(remote_path)

                # Recurse deeper
                self._upload_directory(sftp, local_path, remote_path)
                continue

            # ---- FILE ----
            if entry.lower().endswith(ALLOWED_FILE_EXTS):
                sftp.put(local_path, remote_path)

        self.output_box.append(f"[Upload] Synced MatrixOS core to {remote_dir}")

    def _generate_installer(self, remote_staging, mode, pyflag):
        return f"""#!/bin/bash
    set -e

    echo "[Installer] Local Full Install: syncing MatrixOS from staging…"

    TARGET="/matrix"
    SRC_DIR="{remote_staging}"

    
    # 2) Ensure /matrix exists
    mkdir -p "$TARGET"

    # 3) Use rsync MIRROR MODE to overwrite runtime code
    echo "[Installer] Running rsync mirror…"

    rsync -a --delete \
        "$SRC_DIR"/ "$TARGET"/

    echo "[Installer] rsync complete."

    # 4) Python environment
    if [ "$PYTHON_MODE" = "create" ]; then
    echo "[Installer] Creating fresh venv…"
    rm -rf "$TARGET/venv"
    python3 -m venv "$TARGET/venv"
    source "$TARGET/venv/bin/activate"
    pip install --upgrade pip wheel
    [ -f "$TARGET/requirements.txt" ] && pip install -r "$TARGET/requirements.txt"
    elif [ "$PYTHON_MODE" = "activate" ]; then
    echo "[Installer] Activating existing venv…"
    source "$TARGET/venv/bin/activate" || echo "[WARN] Could not activate venv"
    pip install --upgrade pip wheel || true
    [ -f "$TARGET/requirements.txt" ] && pip install -r "$TARGET/requirements.txt"
    else
    echo "[Installer] Skipping Python setup."
    fi

    # 5) matrixd link
    if [ ! -f "$TARGET/scripts/matrixd" ]; then
    echo "[Installer][ERROR] matrixd script missing under $TARGET/scripts"
    exit 127
    fi

    echo "[Installer] Linking matrixd…"
    rm -f /usr/local/bin/matrixd
    ln -sf "$TARGET/scripts/matrixd" /usr/local/bin/matrixd
    chmod +x "$TARGET/scripts/matrixd"

    echo "[Installer] Local MatrixOS install complete."
    exit 0
    """

    def _generate_github_installer(self, pyflag):
        return f"""#!/bin/bash
set -e

echo "[Installer] GitHub mode: cloning MatrixOS…"

# Ensure required tools
if ! command -v git >/dev/null 2>&1; then
    echo "[Installer] Installing git…"
    apt-get update -y
    apt-get install -y git
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "[Installer] Installing python3…"
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip
fi

echo "[Installer] Cleaning old MatrixOS install…"

echo "[Installer] Cloning repository to /tmp/matrixos-github…"
rm -rf /tmp/matrixos-github
git clone https://github.com/matrixswarm/matrixos.git /tmp/matrixos-github

if [ ! -d /tmp/matrixos-github ]; then
    echo "[Installer][ERROR] Clone failed."
    exit 128
fi

# 4) Overwrite ALL MatrixOS runtime code safely
echo "[Installer] Overwriting runtime directories (preserving universes)…"
cp -r -f /tmp/matrixos-github/. /matrix

cd /matrix

# Python Environment
if [ "{pyflag}" = "create" ]; then
    echo "[Installer] Creating venv…"
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip wheel
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    fi
else
    echo "[Installer] Skipping venv creation."
fi

# matrixd executable
if [ ! -f /matrix/scripts/matrixd ]; then
    echo "[Installer][ERROR] matrixd not found in /matrix/scripts"
    exit 127
fi

echo "[Installer] Linking matrixd globally…"
rm -f /usr/local/bin/matrixd
ln -sf /matrix/scripts/matrixd /usr/local/bin/matrixd
chmod +x /matrix/scripts/matrixd

echo "[Installer] MatrixOS GitHub installation complete."
exit 0
"""


class RemoteTailWorker(QThread):
    new_line = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, client, log_path):
        super().__init__()
        self.client = client
        self.log_path = log_path
        self._running = True

    def run(self):
        import time
        sftp = self.client.open_sftp()

        try:
            while self._running:
                print("running install...")
                try:
                    sftp.stat(self.log_path)
                    break
                except FileNotFoundError:
                    time.sleep(1)

            remote_file = sftp.open(self.log_path, "r")
            remote_file.seek(0, os.SEEK_END)

            while self._running:
                line = remote_file.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                self.new_line.emit(line.rstrip())
        except Exception as e:
            self.new_line.emit(f"[TAIL ERROR] {e}")
        finally:
            sftp.close()
            self.finished.emit()

    def stop(self):
        self._running = False
