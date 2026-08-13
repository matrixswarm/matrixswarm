# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition — Railgun MatrixOS Installer (Operational Core)
import os
import io
import time
import base64
import hmac
from hashlib import sha256
import paramiko
from PyQt6 import QtWidgets
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QTextEdit, QLineEdit, QGroupBox
)
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton


def _clean_secret(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() == "none":
        return None
    return cleaned


def _sha256_fingerprint(key):
    digest = sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii")


def _normalize_fingerprint(value):
    cleaned = _clean_secret(value)
    if not cleaned or not cleaned.startswith("SHA256:"):
        raise ValueError("A trusted SHA256 host-key fingerprint is required")
    return cleaned.rstrip("=")


class _PinnedHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected_fingerprint):
        self.expected = _normalize_fingerprint(expected_fingerprint)

    def missing_host_key(self, client, hostname, key):
        actual = _sha256_fingerprint(key)
        if not hmac.compare_digest(
            self.expected,
            _normalize_fingerprint(actual),
        ):
            raise paramiko.SSHException(
                "SSH host-key fingerprint mismatch for "
                f"{hostname}: expected {self.expected}, "
                f"received {_normalize_fingerprint(actual)}"
            )


def _load_private_key(key_pem, passphrase=None):
    key_text = _clean_secret(key_pem)
    if not key_text:
        raise ValueError("Private key is required for private-key auth")

    password = _clean_secret(passphrase)
    errors = []

    for key_type in (
        paramiko.RSAKey,
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
    ):
        try:
            return key_type.from_private_key(
                io.StringIO(key_text),
                password=password,
            )
        except (
            paramiko.SSHException,
            ValueError,
        ) as exc:
            errors.append(f"{key_type.__name__}: {exc}")

    raise ValueError(
        "Unsupported or invalid private key (RSA, Ed25519, and ECDSA "
        "are supported): " + "; ".join(errors)
    )

class RailgunInstallDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ssh_map = {}
        self.install_modes = [
            "Install from GitHub",
            "Local Full Install",
        ]
        self.tail_thread = None
        self._install_running = False
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
            auth_type = str(
                meta.get("auth_type", "private_key")
            ).strip().lower()

            self.ssh_selector.addItem(f"{label} ({host})", sid)
            self.ssh_map[sid] = {
                "host": host,
                "username": user,
                "port": port,
                "auth_type": auth_type,
                "password": _clean_secret(meta.get("password")),
                "private_key": _clean_secret(meta.get("private_key")),
                "private_key_passphrase": _clean_secret(
                    meta.get("private_key_passphrase")
                ),
                "trusted_host_fingerprint": _clean_secret(
                    meta.get("trusted_host_fingerprint")
                ),
            }

        self.output_box.append(f"[Railgun] Loaded {len(self.ssh_map)} SSH profiles.")

    def _get_selected_ssh(self):
        sid = self.ssh_selector.currentData()
        if not sid:
            return None
        return self.ssh_map.get(sid)

    def run_installer(self):
        if self._install_running:
            self.output_box.append("[Railgun] Installation already in progress.")
            return

        self._install_running = True
        self.btn_install.setEnabled(False)
        client = None
        try:

            selected_sid = self.ssh_selector.currentData()
            if not selected_sid:
                self.output_box.append("[Railgun] No SSH target selected.")
                return

            self._extract_ssh_targets()  # refresh while preserving operator selection

            selected_index = self.ssh_selector.findData(selected_sid)
            if selected_index < 0:
                self.output_box.append(
                    "[Railgun] Selected SSH target is no longer available."
                )
                return

            self.ssh_selector.setCurrentIndex(selected_index)
            self.output_box.append("[Railgun] Starting installation…")
            ssh_cfg = self._get_selected_ssh()
            if not ssh_cfg:
                raise RuntimeError("Selected SSH profile could not be loaded")

            host = ssh_cfg.get("host")
            user = ssh_cfg.get("username")
            if not host or not user:
                raise RuntimeError(
                    "SSH profile is missing host or username"
                )

            client = self._connect_ssh(ssh_cfg)
            if not client:
                raise RuntimeError("SSH connection failed")

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
                    return

                if not os.path.isdir(local_src):
                    self.output_box.append(f"[Railgun] Local path is not a directory: {local_src}")
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
            self.output_box.append(
                f"[Railgun] Installer exited (code={exit_code})"
            )
            if exit_code != 0:
                raise RuntimeError(
                    f"Remote installer failed with exit code {exit_code}"
                )


        except Exception as e:
            self.output_box.append(f"[Railgun ERROR] {e}")
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            self._install_running = False
            self.btn_install.setEnabled(True)

    def _connect_ssh(self, ssh_cfg):
        client = None
        try:
            host = ssh_cfg["host"]
            user = ssh_cfg["username"]
            port = int(ssh_cfg.get("port", 22))
            auth_type = str(
                ssh_cfg.get("auth_type", "private_key")
            ).strip().lower()
            expected_fingerprint = ssh_cfg.get(
                "trusted_host_fingerprint"
            )

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(
                _PinnedHostKeyPolicy(expected_fingerprint)
            )

            connect_args = {
                "hostname": host,
                "port": port,
                "username": user,
                "look_for_keys": False,
                "allow_agent": False,
                "timeout": 15,
                "auth_timeout": 15,
                "banner_timeout": 15,
            }

            if auth_type == "password":
                password = _clean_secret(ssh_cfg.get("password"))
                if not password:
                    raise ValueError(
                        "Password is required for password auth"
                    )
                connect_args["password"] = password
            elif auth_type == "private_key":
                connect_args["pkey"] = _load_private_key(
                    ssh_cfg.get("private_key"),
                    ssh_cfg.get("private_key_passphrase"),
                )
            elif auth_type == "agent":
                connect_args["allow_agent"] = True
            else:
                raise ValueError(
                    f"Unsupported SSH auth type: {auth_type}"
                )

            client.connect(**connect_args)

            server_key = client.get_transport().get_remote_server_key()
            actual_fingerprint = _sha256_fingerprint(server_key)
            if not hmac.compare_digest(
                _normalize_fingerprint(expected_fingerprint),
                _normalize_fingerprint(actual_fingerprint),
            ):
                raise paramiko.SSHException(
                    "SSH host-key fingerprint changed during connection"
                )

            self.output_box.append(
                f"[SSH] Connected to {host} "
                f"({actual_fingerprint})"
            )
            return client
        except Exception as e:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            self.output_box.append(f"[SSH ERROR] {e}")
            return None

    def _create_remote_staging(self, client):
        ts = time.strftime("%Y%m%d_%H%M%S")
        remote = f"/tmp/matrix_staging_{ts}"
        command = f"mkdir -p {remote} && test -d {remote}"
        stdin, stdout, stderr = client.exec_command(command)
        error = stderr.read().decode(errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()

        if exit_code != 0:
            raise RuntimeError(
                f"Failed to create remote staging at {remote}: {error}"
            )

        self.output_box.append(
            f"[Railgun] Remote staging created: {remote}"
        )
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
set -euo pipefail

echo "[Installer] Local Full Install: syncing MatrixOS from staging..."

if [ "$(id -u)" -ne 0 ]; then
    echo "[Installer][ERROR] MatrixOS installation requires root."
    exit 77
fi

if ! command -v python3 >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip
fi

if ! command -v rsync >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y rsync
fi

TARGET="/matrix"
SRC_DIR="{remote_staging}"
VENV_DIR="$TARGET/.venv"

mkdir -p "$TARGET"

echo "[Installer] Replacing runtime code while preserving operator data..."
for runtime_dir in agents core scripts; do
    if [ -d "$SRC_DIR/$runtime_dir" ]; then
        mkdir -p "$TARGET/$runtime_dir"
        rsync -a --delete \
            "$SRC_DIR/$runtime_dir/" "$TARGET/$runtime_dir/"
    fi
done

for preserved_dir in boot_directives maxmind; do
    if [ -d "$SRC_DIR/$preserved_dir" ]; then
        mkdir -p "$TARGET/$preserved_dir"
        rsync -a \
            "$SRC_DIR/$preserved_dir/" "$TARGET/$preserved_dir/"
    fi
done

find "$SRC_DIR" -maxdepth 1 -type f \
    ! -name "install_matrixos.sh" \
    -exec cp -a {{}} "$TARGET/" \;

if [ "$PYTHON_MODE" = "create" ]; then
    echo "[Installer] Creating isolated MatrixOS environment..."
    rm -rf "$VENV_DIR"
    if ! python3 -m venv "$VENV_DIR"; then
        rm -rf "$VENV_DIR"
        apt-get update -y
        apt-get install -y python3-venv python3-pip
        python3 -m venv "$VENV_DIR"
    fi
elif [ "$PYTHON_MODE" = "skip" ]; then
    echo "[Installer] Reusing existing MatrixOS environment..."
    if [ ! -x "$VENV_DIR/bin/python3" ]; then
        echo "[Installer][ERROR] Existing environment not found: $VENV_DIR"
        exit 126
    fi
else
    echo "[Installer][ERROR] Unsupported Python mode: $PYTHON_MODE"
    exit 64
fi

"$VENV_DIR/bin/python3" -m pip install --upgrade pip wheel
if [ -f "$TARGET/requirements.txt" ]; then
    "$VENV_DIR/bin/python3" -m pip install -r "$TARGET/requirements.txt"
fi
"$VENV_DIR/bin/python3" -m pip check

if [ ! -f "$TARGET/scripts/matrixd" ]; then
    echo "[Installer][ERROR] matrixd script missing under $TARGET/scripts"
    exit 127
fi

chmod +x "$TARGET/scripts/matrixd"
"$VENV_DIR/bin/python3" "$TARGET/scripts/matrixd" --help >/dev/null

echo "[Installer] Installing virtual-environment matrixd wrapper..."
printf '%s\n' \
    '#!/bin/sh' \
    'exec /matrix/.venv/bin/python3 /matrix/scripts/matrixd "$@"' \
    > /usr/local/bin/matrixd
chmod 0755 /usr/local/bin/matrixd

echo "[Installer] Local MatrixOS installation complete."
exit 0
"""

    def _generate_github_installer(self, pyflag):
        return f"""#!/bin/bash
set -euo pipefail

echo "[Installer] GitHub mode: cloning MatrixOS..."

if [ "$(id -u)" -ne 0 ]; then
    echo "[Installer][ERROR] MatrixOS installation requires root."
    exit 77
fi

if ! command -v python3 >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip
fi

if ! command -v git >/dev/null 2>&1 || \
   ! command -v rsync >/dev/null 2>&1 || \
   ! command -v flock >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y git rsync util-linux
fi

LOCK_FILE="/tmp/matrixswarm-railgun-install.lock"
exec 9>"$LOCK_FILE"

if ! flock -n 9; then
    echo "[Installer][ERROR] Another Railgun installation is already running."
    exit 75
fi

CLONE_DIR="$(mktemp -d /tmp/matrixswarm-github.XXXXXX)"
trap 'rm -rf "$CLONE_DIR"' EXIT

echo "[Installer] Cloning MatrixSwarm monorepo..."
git clone --depth 1 \
    https://github.com/matrixswarm/matrixswarm.git \
    "$CLONE_DIR"

if [ ! -d "$CLONE_DIR/matrixos" ]; then
    echo "[Installer][ERROR] MatrixOS directory not found after clone."
    exit 128
fi

TARGET="/matrix"
SRC_DIR="$CLONE_DIR/matrixos"
VENV_DIR="$TARGET/.venv"

mkdir -p "$TARGET"

echo "[Installer] Replacing runtime code while preserving operator data..."
for runtime_dir in agents ai core docs scripts sounds teams; do
    if [ -d "$SRC_DIR/$runtime_dir" ]; then
        mkdir -p "$TARGET/$runtime_dir"
        rsync -a --delete \
            "$SRC_DIR/$runtime_dir/" "$TARGET/$runtime_dir/"
    fi
done

for preserved_dir in boot_directives maxmind; do
    if [ -d "$SRC_DIR/$preserved_dir" ]; then
        mkdir -p "$TARGET/$preserved_dir"
        rsync -a \
            "$SRC_DIR/$preserved_dir/" "$TARGET/$preserved_dir/"
    fi
done

find "$SRC_DIR" -maxdepth 1 -type f \
    -exec cp -a {{}} "$TARGET/" \;

if [ "{pyflag}" = "create" ]; then
    echo "[Installer] Creating isolated MatrixOS environment..."
    rm -rf "$VENV_DIR"
    if ! python3 -m venv "$VENV_DIR"; then
        rm -rf "$VENV_DIR"
        apt-get update -y
        apt-get install -y python3-venv python3-pip
        python3 -m venv "$VENV_DIR"
    fi
elif [ "{pyflag}" = "skip" ]; then
    echo "[Installer] Reusing existing MatrixOS environment..."
    if [ ! -x "$VENV_DIR/bin/python3" ]; then
        echo "[Installer][ERROR] Existing environment not found: $VENV_DIR"
        exit 126
    fi
else
    echo "[Installer][ERROR] Unsupported Python mode: {pyflag}"
    exit 64
fi

"$VENV_DIR/bin/python3" -m pip install --upgrade pip wheel
if [ -f "$TARGET/requirements.txt" ]; then
    "$VENV_DIR/bin/python3" -m pip install -r "$TARGET/requirements.txt"
fi
"$VENV_DIR/bin/python3" -m pip check

if [ ! -f "$TARGET/scripts/matrixd" ]; then
    echo "[Installer][ERROR] matrixd not found in $TARGET/scripts"
    exit 127
fi

chmod +x "$TARGET/scripts/matrixd"
"$VENV_DIR/bin/python3" "$TARGET/scripts/matrixd" --help >/dev/null

echo "[Installer] Installing virtual-environment matrixd wrapper..."
printf '%s\n' \
    '#!/bin/sh' \
    'exec /matrix/.venv/bin/python3 /matrix/scripts/matrixd "$@"' \
    > /usr/local/bin/matrixd
chmod 0755 /usr/local/bin/matrixd

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
