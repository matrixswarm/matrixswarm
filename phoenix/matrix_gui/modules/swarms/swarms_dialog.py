"""Top-level Phoenix view of active MatrixOS universes by SSH server."""

from __future__ import annotations

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from matrix_gui.modules.railgun.ssh_support import (
    format_ssh_profile_label,
    load_registry_ssh_profiles,
)
from matrix_gui.modules.swarms.remote import perform


class SwarmOperationWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, profile, operation, universe=None, parent=None):
        super().__init__(parent)
        self.profile = dict(profile)
        self.operation = operation
        self.universe = universe

    def run(self):
        try:
            self.completed.emit(perform(self.profile, self.operation, self.universe))
        except Exception as exc:
            # Do not echo profile fields, credentials, or remote output into UI.
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.profile.clear()


class SwarmsDialog(QDialog):
    """One-shot server inventory; intentionally contains no polling timer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌌 Swarms · Remote MatrixOS")
        self.resize(900, 560)
        self._profiles = {}
        self._worker = None
        self._operation = None
        self._worker_result = None
        self._worker_error = None
        self._universes = []
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(350)
        self._selection_timer.timeout.connect(self.refresh_inventory)
        self.setLayout(self._build_ui())
        self.reload_registry()

    def _build_ui(self):
        layout = QVBoxLayout()
        title = QLabel("🌌 Active swarms by registered SSH server")
        layout.addWidget(title)
        explanation = QLabel(
            "Select a pinned Registry SSH profile to run one matrixd list. "
            "Phoenix does not poll this screen. Kill stops agents only; it does "
            "not delete directives, runtime/static data, or Vault deployments."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Server:"))
        self.previous_btn = QPushButton("▲")
        self.previous_btn.setToolTip("Previous Registry SSH server")
        self.server_combo = QComboBox()
        self.server_combo.setMinimumWidth(520)
        self.next_btn = QPushButton("▼")
        self.next_btn.setToolTip("Next Registry SSH server")
        self.registry_btn = QPushButton("Reload Registry")
        self.refresh_btn = QPushButton("Refresh")
        target_row.addWidget(self.previous_btn)
        target_row.addWidget(self.server_combo, 1)
        target_row.addWidget(self.next_btn)
        target_row.addWidget(self.registry_btn)
        target_row.addWidget(self.refresh_btn)
        layout.addLayout(target_row)

        self.identity_label = QLabel("No server selected.")
        self.identity_label.setWordWrap(True)
        layout.addWidget(self.identity_label)
        self.status_label = QLabel("Load the Registry to begin.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Universe", "Agents", "Memory", "CPU", "Action"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in range(4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.kill_all_btn = QPushButton("⛔ Kill All on This Server")
        self.kill_all_btn.setToolTip(
            "Stop every active universe currently listed on the selected server."
        )
        self.close_btn = QPushButton("Close")
        bottom.addWidget(self.kill_all_btn)
        bottom.addStretch()
        bottom.addWidget(self.close_btn)
        layout.addLayout(bottom)

        self.previous_btn.clicked.connect(lambda: self._step_server(-1))
        self.next_btn.clicked.connect(lambda: self._step_server(1))
        self.registry_btn.clicked.connect(self.reload_registry)
        self.refresh_btn.clicked.connect(self.refresh_inventory)
        self.server_combo.currentIndexChanged.connect(self._server_changed)
        self.kill_all_btn.clicked.connect(self._kill_all)
        self.close_btn.clicked.connect(self.close)
        return layout

    def reload_registry(self):
        if self._worker:
            return
        try:
            profiles = load_registry_ssh_profiles()
        except Exception as exc:
            self._profiles = {}
            self.server_combo.clear()
            self._set_idle()
            QMessageBox.warning(
                self,
                "Unable to Load SSH Registry",
                f"Phoenix could not load the SSH Registry: {type(exc).__name__}",
            )
            return
        selected = self.server_combo.currentData()
        self._profiles = profiles
        self.server_combo.blockSignals(True)
        self.server_combo.clear()
        for serial, profile in profiles.items():
            self.server_combo.addItem(format_ssh_profile_label(serial, profile), serial)
        if selected in profiles:
            self.server_combo.setCurrentIndex(self.server_combo.findData(selected))
        self.server_combo.blockSignals(False)
        self._universes = []
        self._render()
        self._set_idle()
        if profiles:
            self.status_label.setText(
                f"Loaded {len(profiles)} Registry SSH profiles; retrieving selected server once…"
            )
            self._selection_timer.start()
        else:
            self.status_label.setText("No SSH profiles are stored in the Registry.")

    def _server_changed(self, _index):
        self._universes = []
        self._render()
        self._set_identity()
        # Debounce keyboard/arrow traversal so rapid selection does not produce
        # a burst of SSH logins and Gatekeeper notifications.
        self._selection_timer.start()

    def _step_server(self, delta):
        count = self.server_combo.count()
        if count and not self._worker:
            self.server_combo.setCurrentIndex(
                (self.server_combo.currentIndex() + delta) % count
            )

    def _selected_profile(self):
        serial = self.server_combo.currentData()
        profile = self._profiles.get(str(serial))
        return str(serial) if serial is not None else None, dict(profile) if profile else None

    def _set_identity(self, fingerprint=None):
        serial, profile = self._selected_profile()
        if not profile:
            self.identity_label.setText("No server selected.")
            return
        base = format_ssh_profile_label(serial, profile)
        if fingerprint:
            base += f" · verified {fingerprint}"
        self.identity_label.setText(base)

    def _set_busy(self, message):
        self.status_label.setText(message)
        for widget in (
            self.previous_btn,
            self.next_btn,
            self.server_combo,
            self.registry_btn,
            self.refresh_btn,
            self.kill_all_btn,
            self.table,
        ):
            widget.setEnabled(False)

    def _set_idle(self):
        available = bool(self._profiles)
        self.previous_btn.setEnabled(available)
        self.next_btn.setEnabled(available)
        self.server_combo.setEnabled(available)
        self.registry_btn.setEnabled(True)
        self.refresh_btn.setEnabled(available)
        self.kill_all_btn.setEnabled(available and bool(self._universes))
        self.table.setEnabled(True)
        self._set_identity()

    def refresh_inventory(self):
        self._start_operation("list")

    def _start_operation(self, operation, universe=None):
        if self._worker:
            return
        serial, profile = self._selected_profile()
        if not profile:
            self.status_label.setText("Select a Registry SSH server first.")
            return
        self._selection_timer.stop()
        self._operation = operation
        self._worker_result = None
        self._worker_error = None
        action = {
            "list": "Retrieving one-time matrixd inventory",
            "kill": f"Stopping universe '{universe}'",
            "kill_all": "Stopping every listed universe",
        }[operation]
        self._set_busy(f"{action} on {format_ssh_profile_label(serial, profile)}…")
        worker = SwarmOperationWorker(profile, operation, universe, parent=self)
        self._worker = worker
        worker.completed.connect(self._operation_completed)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(self._worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _operation_completed(self, result):
        self._worker_result = result

    def _operation_failed(self, message):
        self._worker_error = message

    def _worker_finished(self):
        operation = self._operation
        result = self._worker_result
        error = self._worker_error
        self._worker = None
        self._operation = None
        self._worker_result = None
        self._worker_error = None
        if error is not None:
            self._set_idle()
            self.status_label.setText(
                "Remote operation failed. The selected account must be root or have "
                "a matching non-interactive sudo grant. " + error
            )
            return
        if not isinstance(result, dict):
            self._set_idle()
            self.status_label.setText("Remote operation ended without a valid result.")
            return
        self._universes = list(result.get("universes", []))
        self._render()
        self._set_idle()
        self._set_identity(result.get("fingerprint"))
        stopped = result.get("stopped", [])
        failed = result.get("failed", [])
        if failed:
            self.status_label.setText(
                f"Stopped {len(stopped)} universe(s); failed to stop: "
                f"{', '.join(failed)}. {len(self._universes)} remain active."
            )
        elif stopped:
            self.status_label.setText(
                f"Stopped {len(stopped)} universe(s): {', '.join(stopped)}. "
                f"{len(self._universes)} remain active on this server."
            )
        elif operation == "list":
            self.status_label.setText(
                f"One-time inventory complete: {len(self._universes)} active universe(s)."
            )

    def _render(self):
        self.table.setRowCount(len(self._universes))
        for row, item in enumerate(self._universes):
            universe = item["universe"]
            memory = f"{item.get('rss_bytes', 0) / 1024 / 1024:.1f} MB"
            values = (
                universe,
                str(item.get("agent_count", 0)),
                memory,
                f"{item.get('cpu_percent', 0):.1f}%",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            host = QWidget()
            actions = QHBoxLayout(host)
            actions.setContentsMargins(0, 0, 0, 0)
            kill_btn = QPushButton("⛔ Kill")
            kill_btn.clicked.connect(lambda _=False, name=universe: self._kill_one(name))
            actions.addWidget(kill_btn)
            actions.addStretch()
            self.table.setCellWidget(row, 4, host)
        self.table.resizeRowsToContents()

    def _kill_one(self, universe):
        serial, profile = self._selected_profile()
        if not profile:
            return
        server = format_ssh_profile_label(serial, profile)
        answer = QMessageBox.question(
            self,
            "Stop Remote Universe?",
            f"Stop every agent in universe '{universe}' on:\n\n{server}\n\n"
            "No directives, runtime/static data, or Vault deployments will be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_operation("kill", universe)

    def _kill_all(self):
        serial, profile = self._selected_profile()
        if not profile or not self._universes:
            return
        server = format_ssh_profile_label(serial, profile)
        text, accepted = QInputDialog.getText(
            self,
            "Kill All Active Universes",
            f"This will stop all {len(self._universes)} active universes on:\n"
            f"{server}\n\nType KILL ALL to continue:",
        )
        if accepted and text == "KILL ALL":
            self._start_operation("kill_all")
        elif accepted:
            QMessageBox.information(self, "Cancelled", "Confirmation did not match.")

    def closeEvent(self, event):
        if self._worker:
            self.status_label.setText("Wait for the active SSH operation to finish before closing.")
            event.ignore()
            return
        super().closeEvent(event)
