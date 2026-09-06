"""Launch an unmodified Phoenix Cockpit with the in-process LLM bridge."""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path

from .session_shim import bridged_run_session


def launch(phoenix_root: Path, data_dir: Path) -> int:
    phoenix_root = phoenix_root.resolve()
    if not all((phoenix_root / name).exists() for name in ("phoenix.py", "matrix_gui", "README.md")):
        raise ValueError(f"not a recognized Phoenix source directory: {phoenix_root}")

    sys.path.insert(0, str(phoenix_root))
    os.chdir(str(phoenix_root))

    import phoenix as phoenix_app
    from PyQt6.QtCore import QTimer, pyqtSignal
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox
    from matrix_gui.core.event_bus import EventBus
    from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton

    from .phoenix_backend import PhoenixBackend
    from .qt_dispatcher import QtBridgeDispatcher
    from .server import BridgeServer

    phoenix_app.run_session = bridged_run_session

    class BridgedPhoenixCockpit(phoenix_app.PhoenixCockpit):
        _llm_activity_requested = pyqtSignal()

        def __init__(self):
            super().__init__()
            self._llm_backend = PhoenixBackend(self, EventBus, VaultCoreSingleton)
            self._llm_dispatcher = QtBridgeDispatcher(self._llm_backend)
            self._llm_server = None

            stale_connection = data_dir / "bridge.json"
            try:
                stale_connection.unlink(missing_ok=True)
            except OSError as exc:
                print(f"[PHOENIX-BRIDGE] Could not remove stale connection file: {exc}")

            bridge_menu = self.menuBar().addMenu("LLM Bridge")
            self._llm_toggle = QAction("Enable LLM Bridge…", self)
            self._llm_toggle.setCheckable(True)
            self._llm_toggle.setChecked(False)
            self._llm_toggle.triggered.connect(self._toggle_llm_bridge)
            bridge_menu.addAction(self._llm_toggle)

            self._llm_status = QLabel("LLM Bridge: OFF")
            self._llm_status.setStyleSheet("color: #777; font-weight: bold;")
            self.statusBar().addPermanentWidget(self._llm_status)
            self._llm_activity_timer = QTimer(self)
            self._llm_activity_timer.setSingleShot(True)
            self._llm_activity_timer.timeout.connect(self._show_llm_ready)
            self._llm_activity_requested.connect(self._show_llm_activity)
            EventBus.on("vault.closed", self._disable_llm_bridge_on_vault_close)
            print("[PHOENIX-BRIDGE] Loaded but OFF. Enable it from the Phoenix LLM Bridge menu after unlocking a vault.")

        def _set_llm_toggle(self, enabled: bool) -> None:
            self._llm_toggle.blockSignals(True)
            self._llm_toggle.setChecked(enabled)
            self._llm_toggle.setText("Disable LLM Bridge" if enabled else "Enable LLM Bridge…")
            self._llm_toggle.blockSignals(False)
            if enabled:
                self._show_llm_ready()
            else:
                self._llm_activity_timer.stop()
                self._llm_status.setText("LLM Bridge: ● OFF")
                self._llm_status.setStyleSheet("color: #777; font-weight: bold;")

        def _show_llm_ready(self) -> None:
            if self._llm_server is None:
                return
            self._llm_status.setText("LLM Bridge: ● ON")
            self._llm_status.setStyleSheet("color: #33cc66; font-weight: bold;")

        def _show_llm_activity(self) -> None:
            if self._llm_server is None:
                return
            self._llm_status.setText("LLM Bridge: ● ACTIVE")
            self._llm_status.setStyleSheet("color: #ffb000; font-weight: bold;")
            self._llm_activity_timer.start(700)

        def _dispatch_llm_request(self, method: str, params: dict) -> dict:
            self._llm_activity_requested.emit()
            return self._llm_dispatcher.call(method, params)

        def _toggle_llm_bridge(self, enabled: bool) -> None:
            if not enabled:
                self._disable_llm_bridge()
                return
            if not self._llm_backend.vault_unlocked:
                QMessageBox.information(self, "Vault required", "Unlock a Phoenix vault before enabling the LLM Bridge.")
                self._set_llm_toggle(False)
                return
            answer = QMessageBox.question(
                self,
                "Enable local LLM Bridge?",
                "Enable the authenticated bridge for this Phoenix session?\n\n"
                "A new one-time token will be created. The LLM can see redacted deployments, agents, "
                "and requested logs, but never vault credentials. Deployment connections still require approval.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._set_llm_toggle(False)
                return
            try:
                self._llm_server = BridgeServer(self._dispatch_llm_request, data_dir)
                info = self._llm_server.start()
                self._set_llm_toggle(True)
                print(
                    f"[PHOENIX-BRIDGE] Enabled on 127.0.0.1:{info['port']} "
                    f"(connection file: {self._llm_server.connection_path})"
                )
            except Exception as exc:
                self._llm_server = None
                self._set_llm_toggle(False)
                QMessageBox.critical(self, "Bridge failed", f"The LLM Bridge could not start:\n{exc}")

        def _disable_llm_bridge(self) -> None:
            if self._llm_server is not None:
                self._llm_server.stop()
                self._llm_server = None
            self._llm_backend.disable_bridge()
            self._set_llm_toggle(False)
            print("[PHOENIX-BRIDGE] Disabled; endpoint removed and capabilities revoked.")

        def _disable_llm_bridge_on_vault_close(self, **_kwargs: object) -> None:
            self._disable_llm_bridge()

        def launch_session(self, session_id: str, deployment: dict, vault_data: dict = None):
            result = super().launch_session(session_id, deployment, vault_data)
            deployment_id = str(deployment.get("id") or session_id)
            deployment_label = str(deployment.get("label") or deployment.get("name") or deployment_id)
            for session in self.session_processes:
                if session.get("session_id") == session_id:
                    session["deployment_id"] = deployment_id
                    session["deployment_label"] = deployment_label
                    break
            return result

        def _handle_session_msg(self, message: dict, conn: object):
            if hasattr(self, "_llm_backend") and self._llm_backend.handle_session_message(message):
                return
            return super()._handle_session_msg(message, conn)

        def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt contract
            EventBus.off("vault.closed", self._disable_llm_bridge_on_vault_close)
            if hasattr(self, "_llm_backend"):
                self._disable_llm_bridge()
            if hasattr(self, "_llm_backend"):
                self._llm_backend.close()
            super().closeEvent(event)

    multiprocessing.freeze_support()
    application = QApplication(sys.argv)
    for stylesheet in ("matrix_gui/theme/icons.qss", "matrix_gui/theme/hive_theme.qss"):
        try:
            application.setStyleSheet((phoenix_root / stylesheet).read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"[PHOENIX-BRIDGE] Could not load {stylesheet}: {exc}")

    phoenix_app.show_with_splash(application, BridgedPhoenixCockpit, delay=1000)
    QTimer.singleShot(0, lambda: print("[PHOENIX-BRIDGE] Launching Phoenix unchanged with bridge hooks."))
    return application.exec()
