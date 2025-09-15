from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QTextEdit, QLineEdit, QPushButton
from PyQt5.QtCore import QSize, QTimer
from PyQt5.QtGui import QIcon, QColor
from matrix_gui.core.event_bus import EventBus
from matrix_gui.config.boot.globals import get_sessions
class PhoenixStaticPanel(QWidget):
    """
    Home HUD after vault unlock:
      - Vault info (path + status)
      - Deployment summary
      - Swarm feed (ops console)
      - Quick ping box
    """
    def __init__(self, vault_data=None, vault_path=None, parent=None):
        super().__init__(parent)
        self.vault_data = vault_data or {}
        self.vault_path = vault_path

        layout = QVBoxLayout(self)


        # === Deployments summary ===
        self.deployments_label = QLabel("Deployments:")
        self.deployments_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.deployments_label)

        self.deployment_summary = QTextEdit()
        self.deployment_summary.setReadOnly(True)
        self.deployment_summary.setStyleSheet( "background:#fff; color:#222; font-family:'Segoe UI', Arial, sans-serif;")
        layout.addWidget(self.deployment_summary)

        self._refresh_deployment_summary()

        # === Swarm Feed ===
        self.feed = QTextEdit()
        self.feed.setReadOnly(True)
        self.feed.setStyleSheet("background:#fff; color:#222; font-family:'Segoe UI', Arial, sans-serif;")
        layout.addWidget(QLabel("🛰️ Swarm Feed"))
        layout.addWidget(self.feed)

        # === Wire EventBus ===
        #EventBus.on("connection.status", self._on_connection_status)
        #EventBus.on("inbound.verified", self._on_inbound_message)

    def _refresh_deployment_summary(self):
        lines = []
        deployments = (self.vault_data or {}).get("deployments", {})
        for dep_id, meta in deployments.items():
            if not isinstance(meta, dict):
                continue
            label = meta.get("label", dep_id)
            lines.append(f"📦 {label}")
            for agent in meta.get("agents", []):
                uid = agent.get("universal_id")
                conn = agent.get("connection", {})
                proto = conn.get("proto", "?")
                host = conn.get("host", "?")
                port = conn.get("port", "?")
                lines.append(f"   └─ {uid} ({proto}) {host}:{port}")
        self.deployment_summary.setPlainText("\n".join(lines) or "[No deployments in vault]")

    def _on_connection_status(self, session_id, channel, status, info, **_):
        line = f"[{channel}] {status} :: sess={session_id} :: {info}"
        self.feed.append(line)

    def _on_inbound_message(self, session_id: str, channel: str, source: str, payload: dict, ts: float, **_):
        import json, time
        t = time.strftime("%H:%M:%S", time.localtime(ts))
        snippet = json.dumps(payload.get("content", payload), separators=(",", ":"), sort_keys=True)[:160]
        line = f"[{t}] ({channel}) {source} » sess={session_id} :: {snippet}"
        self.feed.append(line)
