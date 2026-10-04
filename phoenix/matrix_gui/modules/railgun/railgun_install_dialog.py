# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition — Railgun MatrixOS Installer (Operational Core)
import os
import shlex
import time
from pathlib import Path
from uuid import uuid4
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QTextEdit, QLineEdit, QGroupBox, QProgressBar
)
from matrix_gui.core.class_lib.paths.source_policy import is_environment_path
from matrix_gui.modules.railgun.ssh_support import (
    clean_secret,
    connect_ssh_profile,
    format_ssh_profile_label,
    load_registry_ssh_profiles,
)


class RailgunInstallDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ssh_map = {}
        self.install_modes = [
            "Install from GitHub",
            "Local Full Install",
        ]
        self.install_thread = None
        self._install_running = False
        self._stage = "Ready"
        self._started_at = None
        self._build_ui()
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._refresh_status)
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
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self._browse_local)
        local_layout.addWidget(self.local_path)
        local_layout.addWidget(self.browse_btn)
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

        self.status_label = QLabel("Ready")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.upload_label = QLabel()
        self.upload_label.setTextFormat(Qt.TextFormat.PlainText)
        self.upload_label.setWordWrap(True)
        layout.addWidget(self.upload_label)

        # OUTPUT TERMINAL
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.document().setMaximumBlockCount(5000)
        self.output_box.setStyleSheet(
            "background:#000; color:#0f0; font-family:Consolas,monospace; font-size:12px;"
        )
        layout.addWidget(self.output_box)

        self._append_output("[Railgun] Installer UI ready.")

    def _browse_local(self):
        folder = QFileDialog.getExistingDirectory(self, "Select MatrixOS Root Folder")
        if folder:
            self.local_path.setText(folder)

    def _extract_ssh_targets(self):
        selected_sid = self.ssh_selector.currentData()
        self.ssh_selector.clear()
        self.ssh_map = {}

        try:
            ssh_mgr = load_registry_ssh_profiles()
        except Exception as exc:
            self.ssh_selector.addItem(
                "Unable to load SSH Registry",
                None,
            )
            self._append_output(
                f"[Railgun] Unable to load SSH Registry: {exc}"
            )
            return

        if not ssh_mgr:
            self.ssh_selector.addItem(
                "No SSH profiles in Registry",
                None,
            )
            self._append_output(
                "[Railgun] No SSH profiles found in Registry."
            )
            return

        for sid, meta in ssh_mgr.items():
            host = meta.get("host")
            user = meta.get("username", "root")
            try:
                port = int(meta.get("port", 22))
            except (TypeError, ValueError):
                port = 22
            auth_type = str(
                meta.get("auth_type", "private_key")
            ).strip().lower()

            self.ssh_selector.addItem(
                format_ssh_profile_label(sid, meta),
                sid,
            )
            self.ssh_map[sid] = {
                "host": host,
                "username": user,
                "port": port,
                "auth_type": auth_type,
                "password": clean_secret(meta.get("password")),
                "private_key": clean_secret(meta.get("private_key")),
                "private_key_passphrase": clean_secret(
                    meta.get("private_key_passphrase")
                ),
                "trusted_host_fingerprint": clean_secret(
                    meta.get("trusted_host_fingerprint")
                ),
            }

        if selected_sid:
            selected_index = self.ssh_selector.findData(selected_sid)
            if selected_index >= 0:
                self.ssh_selector.setCurrentIndex(selected_index)

        self._append_output(
            f"[Railgun] Loaded {len(self.ssh_map)} SSH profiles "
            "from Registry."
        )

    def _get_selected_ssh(self):
        sid = self.ssh_selector.currentData()
        if not sid:
            return None
        return self.ssh_map.get(sid)

    def run_installer(self):
        if self._install_running:
            self._append_output("[Railgun] Installation already in progress.")
            return

        selected_sid = self.ssh_selector.currentData()
        if not selected_sid:
            self._append_output("[Railgun] No SSH target selected.")
            return

        # Vault access stays on its owning GUI thread. Only a detached profile
        # snapshot and immutable options cross into the install worker.
        self._extract_ssh_targets()
        selected_index = self.ssh_selector.findData(selected_sid)
        if selected_index < 0:
            self._append_output("[Railgun] Selected SSH target is no longer available.")
            return
        self.ssh_selector.setCurrentIndex(selected_index)
        mode = self.mode_selector.currentText()
        local_src = self.local_path.text().strip()
        if mode == "Local Full Install" and not local_src:
            self._append_output("[Railgun] No local source selected.")
            return

        pyflag = "create" if self.python_mode.currentText() == "Create new venv" else "skip"
        worker = RailgunInstallWorker(self._get_selected_ssh(), mode, local_src, pyflag, self)
        worker.output.connect(self._append_output)
        worker.stage.connect(self._set_stage)
        worker.upload_progress.connect(self._show_upload_progress)
        worker.finished.connect(self._installation_finished)
        self.install_thread = worker
        self._install_running = True
        self._started_at = time.monotonic()
        self.upload_label.clear()
        self._set_controls_enabled(False)
        self._set_stage("Preparing installation")
        self._append_output("[Railgun] Starting installation…")
        self.elapsed_timer.start()
        try:
            worker.start()
        except Exception as exc:
            worker.error = str(exc)
            self._append_output(f"[Railgun ERROR] {exc}")
            self._installation_finished()

    def _set_controls_enabled(self, enabled):
        for widget in (self.mode_selector, self.python_mode, self.local_path,
                       self.browse_btn, self.ssh_selector, self.btn_install):
            widget.setEnabled(enabled)

    @pyqtSlot(str)
    def _append_output(self, text):
        # Server output and file names are plain text, never Qt rich text.
        cursor = self.output_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self.output_box.setTextCursor(cursor)
        self.output_box.ensureCursorVisible()

    @pyqtSlot(str)
    def _set_stage(self, stage):
        self._stage = stage
        self.progress_bar.setRange(0, 0)
        self._refresh_status()

    def _refresh_status(self):
        elapsed = int(time.monotonic() - self._started_at) if self._started_at else 0
        self.status_label.setText(f"{self._stage} · elapsed {elapsed // 60:02d}:{elapsed % 60:02d}")

    @pyqtSlot(object)
    def _show_upload_progress(self, progress):
        done, total, sent, size, path = progress
        self.progress_bar.setRange(0, 1000)
        # Reserve 100% until every put has completed its server-side size check.
        ratio = sent / size if size else (done / total if total else 1)
        value = 1000 if done == total else min(999, int(ratio * 1000))
        self.progress_bar.setValue(value)
        self.upload_label.setText(
            f"Upload: {done:,}/{total:,} files · {_format_bytes(sent)} / {_format_bytes(size)}"
            + (f"\n{path}" if path else "")
        )

    @pyqtSlot()
    def _installation_finished(self):
        worker = self.install_thread
        if worker is None:
            return
        self.elapsed_timer.stop()
        self._install_running = False
        self._stage = "Installation complete" if worker.success else "Installation failed — see log"
        self._refresh_status()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000 if worker.success else 0)
        self._set_controls_enabled(True)
        self.install_thread = None
        worker.deleteLater()

    def _can_close(self):
        if self._install_running:
            self._append_output("[Railgun] Installation is still running. Keep this window open until it finishes.")
            return False
        return True

    def done(self, result):
        if self._can_close():
            super().done(result)

    def reject(self):
        if self._can_close():
            super().reject()

    def closeEvent(self, event):
        if self._can_close():
            super().closeEvent(event)
        else:
            event.ignore()


def _format_bytes(size):
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024


class RailgunInstallWorker(QThread):
    """Own all filesystem/network work; never access GUI widgets from run()."""

    output = pyqtSignal(str)
    stage = pyqtSignal(str)
    upload_progress = pyqtSignal(object)  # Python ints retain large byte counts.
    IO_TIMEOUT = 30

    def __init__(self, ssh_cfg, mode, local_src, pyflag, parent=None):
        super().__init__(parent)
        self.ssh_cfg = dict(ssh_cfg or {})
        self.mode = mode
        self.local_src = local_src
        self.pyflag = pyflag
        self.success = False
        self.error = None

    def _phase(self, message):
        self.stage.emit(message)
        self.output.emit(f"[Railgun] {message}")

    def run(self):
        client = channel = None
        installer_started = False
        try:
            host = self.ssh_cfg.get("host")
            user = self.ssh_cfg.get("username")
            if not host or not user:
                raise ValueError("SSH profile is missing host or username")
            if self.mode not in ("Local Full Install", "Install from GitHub"):
                raise ValueError("Unsupported install mode")
            if self.pyflag not in ("create", "skip"):
                raise ValueError("Unsupported Python mode")

            plan = None
            if self.mode == "Local Full Install":
                self._phase("Scanning local MatrixOS files")
                plan = self._build_upload_plan()

            self._phase(f"Connecting to {user}@{host} — verifying pinned host key")
            client, actual_fingerprint = connect_ssh_profile(self.ssh_cfg)
            self.output.emit(f"[SSH] Connected to {host} ({actual_fingerprint})")
            client.get_transport().set_keepalive(15)
            self._phase("Verifying root or passwordless sudo installation access")
            self._verify_install_privileges(client)
            self._phase("Creating remote staging directory")
            remote_staging = self._create_remote_staging(client)

            if plan is not None:
                self._phase("Uploading MatrixOS files")
                with client.open_sftp() as sftp:
                    sftp.get_channel().settimeout(self.IO_TIMEOUT)
                    self._upload_plan(sftp, plan, remote_staging)
            else:
                self.output.emit("[Railgun] GitHub mode selected — skipping local upload.")

            self._phase("Uploading installer script")
            if self.mode == "Install from GitHub":
                installer_script = self._generate_github_installer(self.pyflag)
            else:
                installer_script = self._generate_installer(remote_staging, self.mode, self.pyflag)

            remote_script = f"{remote_staging}/install_matrixos.sh"
            with client.open_sftp() as sftp:
                sftp.get_channel().settimeout(self.IO_TIMEOUT)
                with sftp.file(remote_script, "w") as f:
                    f.write(installer_script)
                sftp.chmod(remote_script, 0o755)
            self.output.emit(f"[Railgun] Installer uploaded: {remote_script}")

            self._phase("Starting remote installer")
            cmd = self._root_installer_command(remote_script)
            transport = client.get_transport()
            channel = transport.open_session(timeout=self.IO_TIMEOUT)
            channel.settimeout(self.IO_TIMEOUT)
            channel.get_pty()
            installer_started = True
            channel.exec_command(cmd)
            self._phase("Running remote installer")
            exit_code = self._drain_channel(channel, transport)
            self.output.emit(f"[Railgun] Installer exited (code={exit_code})")
            if exit_code != 0:
                raise RuntimeError(f"Remote installer failed with exit code {exit_code}")
            self.success = True
        except Exception as exc:
            self.error = str(exc)
            self.output.emit(f"[Railgun ERROR] {exc}")
            if installer_started:
                self.output.emit("[Railgun] The server may have partial changes. Check the log before retrying; no rollback was performed.")
        finally:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            self.ssh_cfg.clear()

    def _verify_install_privileges(self, client):
        """Fail before upload unless this account can run the fixed installer as root."""
        command = (
            "if [ \"$(id -u)\" -eq 0 ]; then "
            "echo '[Railgun] Root installation access verified.'; "
            "elif command -v sudo >/dev/null 2>&1 && "
            "sudo -n /bin/bash -c 'exit 0' >/dev/null 2>&1; then "
            "echo '[Railgun] Passwordless sudo installation access verified.'; "
            "else echo '[Railgun][ERROR] MatrixOS installation requires root or "
            "passwordless sudo for this SSH account.' >&2; exit 77; fi"
        )
        channel = client.get_transport().open_session(timeout=self.IO_TIMEOUT)
        try:
            channel.settimeout(self.IO_TIMEOUT)
            channel.exec_command(command)
            exit_code = self._drain_channel(
                channel,
                client.get_transport(),
                self.IO_TIMEOUT,
            )
        finally:
            channel.close()
        if exit_code != 0:
            raise PermissionError(
                "Selected SSH account lacks root or passwordless sudo installation access"
            )

    @staticmethod
    def _root_installer_command(remote_script):
        """Run only the uploaded installer, elevating noninteractively when needed."""
        if not isinstance(remote_script, str) or not remote_script.startswith(
            "/tmp/matrix_staging_"
        ) or not remote_script.endswith("/install_matrixos.sh"):
            raise ValueError("Unexpected remote installer path")
        script = shlex.quote(remote_script)
        return (
            "if [ \"$(id -u)\" -eq 0 ]; then "
            f"/bin/bash {script}; "
            "elif command -v sudo >/dev/null 2>&1; then "
            f"sudo -n /bin/bash {script}; "
            "else echo '[Railgun][ERROR] Root or passwordless sudo is required.' "
            ">&2; exit 77; fi"
        )

    def _drain_channel(self, channel, transport, timeout=None):
        started = last_output = time.monotonic()
        waiting = False
        while True:
            received_output = False
            while channel.recv_ready():
                self.output.emit(channel.recv(4096).decode(errors="replace"))
                received_output = True
            while channel.recv_stderr_ready():
                self.output.emit("[ERROR] " + channel.recv_stderr(4096).decode(errors="replace"))
                received_output = True
            if (channel.exit_status_ready()
                    and not channel.recv_ready() and not channel.recv_stderr_ready()):
                return channel.recv_exit_status()
            now = time.monotonic()
            if not transport.is_active() or channel.closed:
                raise ConnectionError("SSH connection closed before command completion")
            if timeout is not None and now - started >= timeout:
                raise TimeoutError("Remote staging command timed out")
            if timeout is None:
                if received_output:
                    last_output = now
                    if waiting:
                        self.stage.emit("Running remote installer")
                    waiting = False
                elif not waiting and now - last_output >= 15:
                    self.stage.emit("Waiting for installer output — remote command has not exited")
                    waiting = True
            time.sleep(0.05)

    def _create_remote_staging(self, client):
        ts = time.strftime("%Y%m%d_%H%M%S")
        remote = f"/tmp/matrix_staging_{ts}_{uuid4().hex[:8]}"
        command = f"mkdir -p {remote} && test -d {remote}"
        channel = client.get_transport().open_session(timeout=self.IO_TIMEOUT)
        try:
            channel.settimeout(self.IO_TIMEOUT)
            channel.exec_command(command)
            exit_code = self._drain_channel(channel, client.get_transport(), self.IO_TIMEOUT)
        finally:
            channel.close()
        if exit_code != 0:
            raise RuntimeError(f"Failed to create remote staging at {remote} (code={exit_code})")
        self.output.emit(f"[Railgun] Remote staging created: {remote}")
        return remote

    def _build_upload_plan(self):
        root = Path(self.local_src)
        if not self.local_src or not root.is_dir():
            raise ValueError("Local source must be a MatrixOS directory")
        allowed_dirs = {"agents", "core", "scripts", "boot_directives", "maxmind"}
        allowed_exts = (".py", ".txt", ".json", ".md", ".sh", ".cfg", ".conf")
        directories, files = [], []

        def scan(directory, flat=False):
            for path in sorted(directory.iterdir()):
                if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    self.output.emit(f"[Upload] Skipping linked path: {path.relative_to(root)}")
                    continue
                relative = path.relative_to(root).as_posix()
                # Apply before both directory recursion and the flat-script rule.
                # Ignore templates too: no environment file belongs in a source upload.
                if is_environment_path(relative):
                    continue
                if path.is_dir():
                    if flat or (directory == root and path.name not in allowed_dirs):
                        continue
                    directories.append(relative)
                    scan(path, flat=path.name in ("scripts", "boot_directives"))
                elif path.is_file() and (flat or path.name.lower().endswith(allowed_exts)):
                    files.append((str(path), relative, path.stat().st_size))

        scan(root)
        if not files:
            raise ValueError("No eligible MatrixOS files found in the selected directory")
        self.output.emit(f"[Upload] Prepared {len(files):,} files ({_format_bytes(sum(f[2] for f in files))})")
        return directories, files

    def _upload_plan(self, sftp, plan, remote_dir):
        directories, files = plan
        total_bytes = sum(f[2] for f in files)
        sent = done = 0
        last_progress = 0.0

        def report(current=0, path="", force=False):
            nonlocal last_progress
            now = time.monotonic()
            if force or now - last_progress >= 0.1:
                self.upload_progress.emit((done, len(files), sent + current, total_bytes, path))
                last_progress = now

        report(force=True)
        for relative in directories:
            sftp.mkdir(f"{remote_dir}/{relative}")
        for local_path, relative, size in files:
            if os.path.getsize(local_path) != size:
                raise RuntimeError(f"Source changed during upload: {relative}; retry with a stable source tree")
            report(path=relative, force=done == 0)
            sftp.put(local_path, f"{remote_dir}/{relative}",
                     callback=lambda current, total: report(min(current, size), relative))
            done += 1
            sent += size
            report(path=relative)
        report(force=True)
        self.output.emit(f"[Upload] Complete: {done:,} files ({_format_bytes(sent)})")

    @staticmethod
    def _python_provisioning_block():
        """Return one pinned, checksum-verified Python 3.12 bootstrap."""
        return r'''PYTHON_VERSION="3.12.15"
PYTHON_SOURCE_SHA256="c2c4321961fab0fb999d66e0cecf521c2ab3994c7992873ea99e306c1094fd5a"
PYTHON_PREFIX="/opt/matrix-python/$PYTHON_VERSION"

find_python312() {
    local candidate
    for candidate in \
        "$(command -v python3.12 || true)" \
        "$PYTHON_PREFIX/bin/python3.12" \
        "$(command -v python3 || true)"; do
        [ -n "$candidate" ] || continue
        if "$candidate" -c 'import ensurepip, ssl, sys, venv; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' \
                >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

install_python312_from_source() {
    echo "[Installer] OS repositories do not provide a complete Python 3.12; building verified Python $PYTHON_VERSION..."
    if command -v dnf >/dev/null 2>&1; then
        install_os_packages gcc make openssl-devel bzip2-devel libffi-devel \
            zlib-devel xz-devel readline-devel sqlite-devel ncurses-devel \
            tar gzip curl ca-certificates
    elif command -v apt-get >/dev/null 2>&1; then
        install_os_packages build-essential pkg-config libssl-dev zlib1g-dev \
            libbz2-dev libreadline-dev libsqlite3-dev libncurses-dev xz-utils \
            libffi-dev liblzma-dev uuid-dev curl ca-certificates
    else
        echo "[Installer][ERROR] Cannot install Python build dependencies on this OS."
        exit 69
    fi

    local build_dir archive source_dir jobs
    build_dir="$(mktemp -d /tmp/matrix-python-build.XXXXXXXX)"
    archive="$build_dir/Python-$PYTHON_VERSION.tar.xz"
    source_dir="$build_dir/Python-$PYTHON_VERSION"
    trap 'rm -rf "$build_dir"' EXIT
    curl --fail --location --proto '=https' --tlsv1.2 \
        --output "$archive" \
        "https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tar.xz"
    printf '%s  %s\n' "$PYTHON_SOURCE_SHA256" "$archive" | sha256sum -c -
    tar -xJf "$archive" -C "$build_dir"
    cd "$source_dir"
    ./configure --prefix="$PYTHON_PREFIX" --with-ensurepip=install
    jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
    case "$jobs" in ''|*[!0-9]*) jobs=2 ;; esac
    [ "$jobs" -le 8 ] || jobs=8
    make -j "$jobs"
    rm -rf "$PYTHON_PREFIX"
    make altinstall
    ln -sfn "$PYTHON_PREFIX/bin/python3.12" /usr/local/bin/python3.12
    cd /
    rm -rf "$build_dir"
    trap - EXIT
}

PYTHON_BIN="$(find_python312 || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "[Installer] Python 3.12 not found; trying the OS package manager..."
    if command -v dnf >/dev/null 2>&1; then
        if ! dnf install -y python3.12 python3.12-pip; then
            echo "[Installer] Python 3.12 packages are unavailable; source fallback required."
        fi
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update -y
        if ! DEBIAN_FRONTEND=noninteractive apt-get install -y \
                python3.12 python3.12-venv; then
            echo "[Installer] Python 3.12 packages are unavailable; source fallback required."
        fi
    fi
    PYTHON_BIN="$(find_python312 || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
    install_python312_from_source
    PYTHON_BIN="$(find_python312 || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
    echo "[Installer][ERROR] Verified Python 3.12 provisioning failed."
    exit 65
fi
if ! "$PYTHON_BIN" -c 'import ensurepip, ssl, sys, venv; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
    echo "[Installer][ERROR] $PYTHON_BIN is not a complete Python 3.12 runtime."
    exit 65
fi
echo "[Installer] Selected Python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"'''

    def _generate_installer(self, remote_staging, mode, pyflag):
        python_bootstrap = self._python_provisioning_block()
        return f"""#!/bin/bash
set -euo pipefail
PYTHON_MODE={pyflag}

echo "[Installer] Local Full Install: syncing MatrixOS from staging..."

if [ "$(id -u)" -ne 0 ]; then
    echo "[Installer][ERROR] MatrixOS installation requires root."
    exit 77
fi

install_os_packages() {{
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y "$@"
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update -y
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
    else
        echo "[Installer][ERROR] Supported package manager (dnf or apt-get) not found."
        exit 69
    fi
}}

{python_bootstrap}

if ! command -v rsync >/dev/null 2>&1 || \
   ! command -v sudo >/dev/null 2>&1 || \
   ! command -v setfacl >/dev/null 2>&1; then
    install_os_packages rsync sudo acl
fi
if ! command -v ssh >/dev/null 2>&1 || \
   ! command -v ssh-keyscan >/dev/null 2>&1 || \
   ! command -v ssh-keygen >/dev/null 2>&1; then
    if [ -x /usr/bin/dnf ]; then
        dnf install -y openssh-clients
    else
        apt-get update -y
        DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-client
    fi
fi
if ! command -v sshpass >/dev/null 2>&1; then
    install_os_packages sshpass
fi

TARGET="/matrix"
SRC_DIR="{remote_staging}"
VENV_DIR="$TARGET/.venv"

harden_matrix_install() {{
    echo "[Installer] Hardening shared MatrixOS source..."
    install -d "$TARGET"
    if [ -L "$TARGET" ]; then
        echo "[Installer][ERROR] Refusing a symlinked MatrixOS root: $TARGET"
        exit 77
    fi
    setfacl -b -- "$TARGET"
    chown root:root "$TARGET"
    chmod 0755 "$TARGET"

    for SOURCE_PATH in \
        "$TARGET/agents" "$TARGET/ai" "$TARGET/core" \
        "$TARGET/docs" "$TARGET/scripts" "$TARGET/sounds" \
        "$TARGET/teams" "$TARGET/.venv" "$TARGET/mcp/.venv"; do
        [ -e "$SOURCE_PATH" ] || continue
        if [ -L "$SOURCE_PATH" ]; then
            echo "[Installer][ERROR] Refusing a symlinked source root: $SOURCE_PATH"
            exit 77
        fi
        setfacl -R -P -b -- "$SOURCE_PATH"
        chown -hR root:root "$SOURCE_PATH"
        find "$SOURCE_PATH" -xdev -type d -exec chmod a+rx,go-w {{}} +
        find "$SOURCE_PATH" -xdev -type f -exec chmod a+r,go-w {{}} +
    done

    find "$TARGET" -maxdepth 1 -type f -exec setfacl -b -- {{}} +
    find "$TARGET" -maxdepth 1 -type f -exec chown root:root -- {{}} +
    find "$TARGET" -maxdepth 1 -type f -exec chmod a+r,go-w -- {{}} +

    for BOUNDARY_PATH in "$TARGET/universes" "$TARGET/universes/runtime" \
        "$TARGET/universes/static" "$TARGET/mcp" "$TARGET/mcp/workers"; do
        if [ -L "$BOUNDARY_PATH" ]; then
            echo "[Installer][ERROR] Refusing a symlinked mutable boundary: $BOUNDARY_PATH"
            exit 77
        fi
    done
    install -d "$TARGET/universes" "$TARGET/universes/runtime" \
        "$TARGET/universes/static" "$TARGET/mcp" "$TARGET/mcp/workers"
    chown root:root "$TARGET/universes" "$TARGET/universes/runtime" \
        "$TARGET/universes/static" "$TARGET/mcp" "$TARGET/mcp/workers"
    chmod 0711 "$TARGET/universes" "$TARGET/universes/runtime" \
        "$TARGET/universes/static" "$TARGET/mcp" "$TARGET/mcp/workers"
}}

# Close any permissions left by an older installation before replacement, then
# repeat after package installation to cover every newly written source file.
harden_matrix_install

echo "[Installer] Replacing runtime code while preserving operator data..."
for runtime_dir in agents core scripts; do
    if [ -d "$SRC_DIR/$runtime_dir" ]; then
        mkdir -p "$TARGET/$runtime_dir"
        rsync -a --delete \
            --exclude='.[eE][nN][vV]*' --exclude='*.[eE][nN][vV]' --exclude='*.[eE][nN][vV].*' \
            "$SRC_DIR/$runtime_dir/" "$TARGET/$runtime_dir/"
    fi
done

for preserved_dir in boot_directives maxmind; do
    if [ -d "$SRC_DIR/$preserved_dir" ]; then
        mkdir -p "$TARGET/$preserved_dir"
        rsync -a \
            --exclude='.[eE][nN][vV]*' --exclude='*.[eE][nN][vV]' --exclude='*.[eE][nN][vV].*' \
            "$SRC_DIR/$preserved_dir/" "$TARGET/$preserved_dir/"
    fi
done

find "$SRC_DIR" -maxdepth 1 -type f \
    ! -iname '.env*' ! -iname '*.env' ! -iname '*.env.*' \
    ! -name "install_matrixos.sh" \
    -exec cp -a {{}} "$TARGET/" \\;

if [ "$PYTHON_MODE" = "create" ]; then
    echo "[Installer] Creating isolated MatrixOS environment..."
    rm -rf "$VENV_DIR"
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        rm -rf "$VENV_DIR"
        echo "[Installer][ERROR] Python 3.12 venv support is unavailable."
        exit 70
    fi
elif [ "$PYTHON_MODE" = "skip" ]; then
    echo "[Installer] Reusing existing MatrixOS environment..."
    if [ ! -x "$VENV_DIR/bin/python3" ]; then
        echo "[Installer][ERROR] Existing environment not found: $VENV_DIR"
        exit 126
    fi
    if ! "$VENV_DIR/bin/python3" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
        echo "[Installer][ERROR] Existing MatrixOS environment uses Python older than 3.12."
        exit 65
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

MCP_REQUIREMENTS="$TARGET/agents/python_core/mcp_reflex/worker/requirements.txt"
MCP_LAUNCHER="$TARGET/scripts/matrix-mcp-launch"
if [ -f "$MCP_REQUIREMENTS" ]; then
    echo "[Installer] Creating isolated MCP worker environment..."
    # Windows working copies may arrive with CRLF even for executable Python
    # sources. Normalize the sealed boundary before hashing or installation.
    find "$TARGET/agents/python_core/mcp_reflex" -type f -name '*.py' \
        -exec sed -i 's/\\r$//' {{}} +
    sed -i 's/\\r$//' "$MCP_LAUNCHER"
    MCP_VENV="$TARGET/mcp/.venv"
    install -d -o root -g root -m 0711 "$TARGET/mcp/workers"
    rm -rf "$MCP_VENV"
    "$PYTHON_BIN" -m venv "$MCP_VENV"
    "$MCP_VENV/bin/python3" -m pip install --upgrade pip wheel
    "$MCP_VENV/bin/python3" -m pip install -r "$MCP_REQUIREMENTS"
    "$MCP_VENV/bin/python3" -m pip check

    if [ ! -f "$MCP_LAUNCHER" ]; then
        echo "[Installer][ERROR] MCP privilege-drop launcher is missing."
        exit 127
    fi
    install -d -o root -g root -m 0755 /usr/local/libexec
    install -o root -g root -m 0755 \
        "$MCP_LAUNCHER" /usr/local/libexec/matrix-mcp-launch
    chown -R root:root "$TARGET/mcp" "$TARGET/agents/python_core/mcp_reflex"
    find "$TARGET/mcp" "$TARGET/agents/python_core/mcp_reflex" \
        -type d -exec chmod go-w {{}} +
    find "$TARGET/mcp" "$TARGET/agents/python_core/mcp_reflex" \
        -type f -exec chmod go-w {{}} +
fi

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

harden_matrix_install

echo "[Installer] Local MatrixOS installation complete."
exit 0
"""

    def _generate_github_installer(self, pyflag):
        python_bootstrap = self._python_provisioning_block()
        return f"""#!/bin/bash
set -euo pipefail
PYTHON_MODE={pyflag}

echo "[Installer] GitHub mode: cloning MatrixOS..."

if [ "$(id -u)" -ne 0 ]; then
    echo "[Installer][ERROR] MatrixOS installation requires root."
    exit 77
fi

install_os_packages() {{
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y "$@"
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update -y
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
    else
        echo "[Installer][ERROR] Supported package manager (dnf or apt-get) not found."
        exit 69
    fi
}}

{python_bootstrap}

if ! command -v git >/dev/null 2>&1 || \
   ! command -v rsync >/dev/null 2>&1 || \
   ! command -v flock >/dev/null 2>&1 || \
   ! command -v sudo >/dev/null 2>&1 || \
   ! command -v setfacl >/dev/null 2>&1; then
    install_os_packages git rsync util-linux sudo acl
fi
if ! command -v ssh >/dev/null 2>&1 || \
   ! command -v ssh-keyscan >/dev/null 2>&1 || \
   ! command -v ssh-keygen >/dev/null 2>&1; then
    if [ -x /usr/bin/dnf ]; then
        dnf install -y openssh-clients
    else
        apt-get update -y
        DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-client
    fi
fi
if ! command -v sshpass >/dev/null 2>&1; then
    install_os_packages sshpass
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

harden_matrix_install() {{
    echo "[Installer] Hardening shared MatrixOS source..."
    install -d "$TARGET"
    if [ -L "$TARGET" ]; then
        echo "[Installer][ERROR] Refusing a symlinked MatrixOS root: $TARGET"
        exit 77
    fi
    setfacl -b -- "$TARGET"
    chown root:root "$TARGET"
    chmod 0755 "$TARGET"

    for SOURCE_PATH in \
        "$TARGET/agents" "$TARGET/ai" "$TARGET/core" \
        "$TARGET/docs" "$TARGET/scripts" "$TARGET/sounds" \
        "$TARGET/teams" "$TARGET/.venv" "$TARGET/mcp/.venv"; do
        [ -e "$SOURCE_PATH" ] || continue
        if [ -L "$SOURCE_PATH" ]; then
            echo "[Installer][ERROR] Refusing a symlinked source root: $SOURCE_PATH"
            exit 77
        fi
        setfacl -R -P -b -- "$SOURCE_PATH"
        chown -hR root:root "$SOURCE_PATH"
        find "$SOURCE_PATH" -xdev -type d -exec chmod a+rx,go-w {{}} +
        find "$SOURCE_PATH" -xdev -type f -exec chmod a+r,go-w {{}} +
    done

    find "$TARGET" -maxdepth 1 -type f -exec setfacl -b -- {{}} +
    find "$TARGET" -maxdepth 1 -type f -exec chown root:root -- {{}} +
    find "$TARGET" -maxdepth 1 -type f -exec chmod a+r,go-w -- {{}} +

    for BOUNDARY_PATH in "$TARGET/universes" "$TARGET/universes/runtime" \
        "$TARGET/universes/static" "$TARGET/mcp" "$TARGET/mcp/workers"; do
        if [ -L "$BOUNDARY_PATH" ]; then
            echo "[Installer][ERROR] Refusing a symlinked mutable boundary: $BOUNDARY_PATH"
            exit 77
        fi
    done
    install -d "$TARGET/universes" "$TARGET/universes/runtime" \
        "$TARGET/universes/static" "$TARGET/mcp" "$TARGET/mcp/workers"
    chown root:root "$TARGET/universes" "$TARGET/universes/runtime" \
        "$TARGET/universes/static" "$TARGET/mcp" "$TARGET/mcp/workers"
    chmod 0711 "$TARGET/universes" "$TARGET/universes/runtime" \
        "$TARGET/universes/static" "$TARGET/mcp" "$TARGET/mcp/workers"
}}

# Close any permissions left by an older installation before replacement, then
# repeat after package installation to cover every newly written source file.
harden_matrix_install

echo "[Installer] Replacing runtime code while preserving operator data..."
for runtime_dir in agents ai core docs scripts sounds teams; do
    if [ -d "$SRC_DIR/$runtime_dir" ]; then
        mkdir -p "$TARGET/$runtime_dir"
        rsync -a --delete \
            --exclude='.[eE][nN][vV]*' --exclude='*.[eE][nN][vV]' --exclude='*.[eE][nN][vV].*' \
            "$SRC_DIR/$runtime_dir/" "$TARGET/$runtime_dir/"
    fi
done

for preserved_dir in boot_directives maxmind; do
    if [ -d "$SRC_DIR/$preserved_dir" ]; then
        mkdir -p "$TARGET/$preserved_dir"
        rsync -a \
            --exclude='.[eE][nN][vV]*' --exclude='*.[eE][nN][vV]' --exclude='*.[eE][nN][vV].*' \
            "$SRC_DIR/$preserved_dir/" "$TARGET/$preserved_dir/"
    fi
done

find "$SRC_DIR" -maxdepth 1 -type f \
    ! -iname '.env*' ! -iname '*.env' ! -iname '*.env.*' \
    -exec cp -a {{}} "$TARGET/" \\;

if [ "{pyflag}" = "create" ]; then
    echo "[Installer] Creating isolated MatrixOS environment..."
    rm -rf "$VENV_DIR"
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        rm -rf "$VENV_DIR"
        echo "[Installer][ERROR] Python 3.12 venv support is unavailable."
        exit 70
    fi
elif [ "{pyflag}" = "skip" ]; then
    echo "[Installer] Reusing existing MatrixOS environment..."
    if [ ! -x "$VENV_DIR/bin/python3" ]; then
        echo "[Installer][ERROR] Existing environment not found: $VENV_DIR"
        exit 126
    fi
    if ! "$VENV_DIR/bin/python3" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
        echo "[Installer][ERROR] Existing MatrixOS environment uses Python older than 3.12."
        exit 65
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

MCP_REQUIREMENTS="$TARGET/agents/python_core/mcp_reflex/worker/requirements.txt"
MCP_LAUNCHER="$TARGET/scripts/matrix-mcp-launch"
if [ -f "$MCP_REQUIREMENTS" ]; then
    echo "[Installer] Creating isolated MCP worker environment..."
    # Windows working copies may arrive with CRLF even for executable Python
    # sources. Normalize the sealed boundary before hashing or installation.
    find "$TARGET/agents/python_core/mcp_reflex" -type f -name '*.py' \
        -exec sed -i 's/\\r$//' {{}} +
    sed -i 's/\\r$//' "$MCP_LAUNCHER"
    MCP_VENV="$TARGET/mcp/.venv"
    install -d -o root -g root -m 0711 "$TARGET/mcp/workers"
    rm -rf "$MCP_VENV"
    "$PYTHON_BIN" -m venv "$MCP_VENV"
    "$MCP_VENV/bin/python3" -m pip install --upgrade pip wheel
    "$MCP_VENV/bin/python3" -m pip install -r "$MCP_REQUIREMENTS"
    "$MCP_VENV/bin/python3" -m pip check

    if [ ! -f "$MCP_LAUNCHER" ]; then
        echo "[Installer][ERROR] MCP privilege-drop launcher is missing."
        exit 127
    fi
    install -d -o root -g root -m 0755 /usr/local/libexec
    install -o root -g root -m 0755 \
        "$MCP_LAUNCHER" /usr/local/libexec/matrix-mcp-launch
    chown -R root:root "$TARGET/mcp" "$TARGET/agents/python_core/mcp_reflex"
    find "$TARGET/mcp" "$TARGET/agents/python_core/mcp_reflex" \
        -type d -exec chmod go-w {{}} +
    find "$TARGET/mcp" "$TARGET/agents/python_core/mcp_reflex" \
        -type f -exec chmod go-w {{}} +
fi

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

harden_matrix_install

echo "[Installer] MatrixOS GitHub installation complete."
exit 0
"""
