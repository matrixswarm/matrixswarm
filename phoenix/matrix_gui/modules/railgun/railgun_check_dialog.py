# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition — Railgun Remote Host Recon
import socket

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QTextEdit, QMessageBox
)
from matrix_gui.modules.railgun.ssh_support import (
    connect_ssh_profile,
    load_registry_ssh_profiles,
)


class RailgunCheckWorker(QThread):
    """Run bounded remote checks without blocking Qt's event loop."""

    output = pyqtSignal(str)

    COMMAND_TIMEOUT = 12

    def __init__(self, ssh_cfg, checks, parent=None):
        super().__init__(parent)
        self.ssh_cfg = dict(ssh_cfg)
        self.checks = tuple(checks)
        self.client = None
        self.success = False

    def cancel(self):
        self.requestInterruption()
        client = self.client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def _run_command(self, command):
        if self.isInterruptionRequested():
            return None

        try:
            _stdin, stdout, stderr = self.client.exec_command(
                command,
                timeout=self.COMMAND_TIMEOUT,
            )
            stdout.channel.settimeout(self.COMMAND_TIMEOUT)
            out = stdout.read().decode(errors="replace").strip()
            err = stderr.read().decode(errors="replace").strip()
        except (socket.timeout, TimeoutError):
            self.output.emit(
                "<span style='color:red'>[SSH ERROR] Remote command "
                "timed out.</span>"
            )
            return None
        except Exception as exc:
            self.output.emit(
                f"<span style='color:red'>[SSH ERROR] {exc}</span>"
            )
            return None

        if out:
            self.output.emit(out)
        if err:
            self.output.emit(f"<span style='color:red'>{err}</span>")
        return out

    def _check_ssh(self):
        self.output.emit("[Check] Testing SSH connectivity…")
        self.output.emit("[OK] SSH connection established.")
        return True

    def _check_os(self):
        self.output.emit("[Check] Detecting OS…")
        response = self._run_command("cat /etc/os-release")
        if response is None:
            return False
        if "Ubuntu" in response or "Debian" in response:
            self.output.emit("[OK] OS: Debian/Ubuntu family")
        elif (
            "CentOS" in response
            or "Rocky" in response
            or "Red Hat" in response
        ):
            self.output.emit("[OK] OS: RHEL/CentOS/Rocky family")
        else:
            self.output.emit(
                "<span style='color:yellow'>[WARN] Unknown OS type</span>"
            )
        return True

    def _check_python(self):
        self.output.emit("[Check] Looking for Python 3.12…")
        response = self._run_command("command -v python3.12 || true")
        if response is None:
            return False
        if response:
            version = self._run_command("python3.12 --version 2>&1 || true")
            if version is None:
                return False
            self.output.emit(f"[OK] Found {version} at {response}")
        else:
            self.output.emit(
                "<span style='color:red'>[FAIL] Python 3.12 not found; "
                "Railgun will refuse installation.</span>"
            )

        self.output.emit("[Check] Checking pip…")
        response = self._run_command(
            "python3.12 -m pip --version 2>/dev/null || true"
        )
        if response is None:
            return False
        if response:
            self.output.emit(f"[OK] Found pip at {response}")
        else:
            self.output.emit(
                "<span style='color:red'>"
                "[FAIL] Python 3.12 pip not found.</span>"
            )

        self.output.emit("[Check] Checking venv…")
        response = self._run_command(
            "python3.12 -m venv --help >/dev/null 2>&1 "
            "&& echo OK || echo FAIL"
        )
        if response is None:
            return False
        if response == "OK":
            self.output.emit("[OK] venv available")
        else:
            self.output.emit(
                "<span style='color:red'>[FAIL] venv module missing</span>"
            )
        return True

    def _check_matrix_path(self):
        self.output.emit("[Check] Checking /matrix directory…")
        response = self._run_command(
            "[ -d /matrix ] && echo EXISTS || echo NO"
        )
        if response is None:
            return False
        if response == "EXISTS":
            self.output.emit("[OK] /matrix exists")
        else:
            self.output.emit(
                "[INFO] /matrix missing (will be created by installer)"
            )
        return True

    def _check_disk(self):
        self.output.emit("[Check] Checking disk space…")
        response = self._run_command("df -h / | tail -1 | awk '{print $4}'")
        if response is None:
            return False
        if response:
            self.output.emit(f"[OK] Free space: {response}")
        else:
            self.output.emit(
                "<span style='color:red'>[FAIL] Disk check returned no data.</span>"
            )
        return True

    def _check_clock(self):
        self.output.emit("[Check] Checking system clock…")
        response = self._run_command("date --iso-8601=seconds")
        if response is None:
            return False
        if response:
            self.output.emit(f"[OK] System time: {response}")
        else:
            self.output.emit(
                "<span style='color:red'>[FAIL] Clock check returned no data.</span>"
            )
        return True

    def _check_existing(self):
        self.output.emit("[Check] Looking for existing MatrixOS install…")
        response = self._run_command(
            "if [ -f /matrix/scripts/matrixd ] "
            "|| [ -x /usr/local/bin/matrixd ]; then echo YES; else echo NO; fi"
        )
        if response is None:
            return False
        if response == "YES":
            self.output.emit(
                "<span style='color:yellow'>"
                "[WARN] MatrixOS already installed.</span>"
            )
        else:
            self.output.emit("[OK] No existing MatrixOS detected.")
        return True

    def run(self):
        try:
            self.client, actual_fingerprint = connect_ssh_profile(
                self.ssh_cfg,
                timeout=self.COMMAND_TIMEOUT,
            )
            self.output.emit(
                f"[SSH] Verified host fingerprint: {actual_fingerprint}"
            )
        except Exception as exc:
            self.output.emit(
                f"<span style='color:red'>[SSH ERROR] {exc}</span>"
            )
            self.output.emit(
                "<span style='color:red'>"
                "[FAIL] Recon aborted; no remote checks were executed.</span>"
            )
            return

        handlers = {
            "ssh": self._check_ssh,
            "os": self._check_os,
            "python": self._check_python,
            "matrix_path": self._check_matrix_path,
            "disk": self._check_disk,
            "clock": self._check_clock,
            "existing": self._check_existing,
        }

        try:
            for check_name in self.checks:
                if self.isInterruptionRequested():
                    return
                if not handlers[check_name]():
                    self.output.emit(
                        "<span style='color:red'>"
                        "[FAIL] Recon stopped after a remote command failure."
                        "</span>"
                    )
                    return
            self.success = True
        finally:
            if self.client is not None:
                self.client.close()
                self.client = None


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
        self.refresh_targets()

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

        self._action_buttons = (
            self.btn_run_all,
            self.btn_check_ssh,
            self.btn_check_os,
            self.btn_check_python,
            self.btn_check_matrix_path,
            self.btn_disk,
            self.btn_clock,
            self.btn_existing,
        )

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

        self._worker = None

    # -----------------------------------------------------
    # SSH INIT
    # -----------------------------------------------------
    def refresh_targets(self):
        selected_serial = self.ssh_selector.currentData(
            Qt.ItemDataRole.UserRole + 1
        )
        self.ssh_selector.clear()

        try:
            ssh_map = load_registry_ssh_profiles()
        except Exception:
            self.ssh_selector.addItem(
                "Unable to load SSH Registry",
                None,
            )
            return

        if not ssh_map:
            self.ssh_selector.addItem(
                "No SSH profiles in Registry",
                None,
            )
            return

        for serial, meta in ssh_map.items():
            label = meta.get("label", serial)
            self.ssh_selector.addItem(
                f"{label} ({meta.get('host')})",
                meta,
            )
            item_index = self.ssh_selector.count() - 1
            self.ssh_selector.setItemData(
                item_index,
                serial,
                Qt.ItemDataRole.UserRole + 1,
            )
            if serial == selected_serial:
                self.ssh_selector.setCurrentIndex(item_index)

    def _set_check_controls_enabled(self, enabled):
        self.ssh_selector.setEnabled(enabled)
        for button in self._action_buttons:
            button.setEnabled(enabled)

    def _start_checks(self, checks, heading=None):
        if self._worker is not None and self._worker.isRunning():
            self.output_box.append("[Railgun] A remote check is already running.")
            return

        ssh_cfg = self.ssh_selector.currentData()
        if not ssh_cfg:
            QMessageBox.critical(
                self,
                "No SSH Target",
                "No SSH target found in the SSH Registry.",
            )
            return

        if heading:
            self.output_box.append(heading)

        self._set_check_controls_enabled(False)
        self._worker = RailgunCheckWorker(ssh_cfg, checks, parent=self)
        self._worker.output.connect(self.output_box.append)
        self._worker.finished.connect(self._checks_finished)
        self._worker.start()

    def _checks_finished(self):
        worker = self._worker
        if worker is None:
            return

        if worker.isInterruptionRequested():
            self.output_box.append("[Railgun] Recon cancelled.")
        elif worker.success:
            self.output_box.append("\n⚡ <b>Recon Complete.</b>\n")

        self._set_check_controls_enabled(True)
        worker.deleteLater()
        self._worker = None

    # -----------------------------------------------------
    # CHECKS
    # -----------------------------------------------------
    def check_ssh(self):
        self._start_checks(("ssh",))

    def check_os(self):
        self._start_checks(("os",))

    def check_python(self):
        self._start_checks(("python",))

    def check_matrix_path(self):
        self._start_checks(("matrix_path",))

    def check_disk(self):
        self._start_checks(("disk",))

    def check_clock(self):
        self._start_checks(("clock",))

    def check_existing(self):
        self._start_checks(("existing",))

    # -----------------------------------------------------
    # RUN ALL
    # -----------------------------------------------------
    def _run_all(self):
        self._start_checks(
            (
                "ssh",
                "os",
                "python",
                "matrix_path",
                "disk",
                "clock",
                "existing",
            ),
            heading="\n⚡ <b>Running Full Recon...</b>\n",
        )

    def closeEvent(self, event):
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            if not worker.wait(3000):
                self.output_box.append(
                    "[Railgun] Waiting for the active SSH operation to stop…"
                )
                event.ignore()
                return
        event.accept()
