from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QTextEdit, QLineEdit, QPushButton
from matrix_gui.core.class_lib.feed.feed_formatter import FeedFormatter
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu
from PyQt5.QtCore import Qt
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

        self.deployment_tree = QTreeWidget()
        self.deployment_tree.setHeaderHidden(True)
        self.deployment_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.deployment_tree.customContextMenuRequested.connect(self._on_deployment_context_menu)
        layout.addWidget(self.deployment_tree)

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
        self.deployment_tree.clear()
        deployments = (self.vault_data or {}).get("deployments", {})
        for dep_id, meta in deployments.items():
            if not isinstance(meta, dict):
                continue
            label = meta.get("label", dep_id)
            dep_item = QTreeWidgetItem([f"📦 {label}"])
            dep_item.setData(0, Qt.UserRole, {"dep_id": dep_id, "meta": meta})
            self.deployment_tree.addTopLevelItem(dep_item)

            for agent in meta.get("agents", []):
                uid = agent.get("universal_id")
                conn = agent.get("connection", {})
                proto = conn.get("proto", "?")
                host = conn.get("host", "?")
                port = conn.get("port", "?")
                child = QTreeWidgetItem([f"{uid} ({proto}) {host}:{port}"])
                dep_item.addChild(child)

    def _on_connection_status(self, session_id, channel, status, info, **_):
        line = f"[{channel}] {status} :: sess={session_id} :: {info}"
        self.feed.append(line)

    def append_feed_event(self, event: dict):
        """Append a formatted event to the Swarm Feed console."""
        try:
            msg = FeedFormatter.format(event)
            self.feed.append(msg)
        except Exception as e:
            self.feed.append(f"[FEED][ERROR] Could not format event: {e}")

    def _on_inbound_message(self, session_id: str, channel: str, source: str, payload: dict, ts: float, **_):
        import json, time
        t = time.strftime("%H:%M:%S", time.localtime(ts))
        snippet = json.dumps(payload.get("content", payload), separators=(",", ":"), sort_keys=True)[:160]
        line = f"[{t}] ({channel}) {source} » sess={session_id} :: {snippet}"
        self.feed.append(line)

    def _on_deployment_context_menu(self, pos):
        item = self.deployment_tree.itemAt(pos)
        if not item:
            return

        data = item.data(0, Qt.UserRole)
        if not data:
            return  # only top-level deployment nodes

        menu = QMenu(self)
        act_connect = menu.addAction("🔌 Connect")
        act_connect.triggered.connect(lambda: self._connect_deployment(data))
        menu.exec_(self.deployment_tree.viewport().mapToGlobal(pos))

    def _connect_deployment(self, data):
        dep_id = data["dep_id"]
        meta = data["meta"]
        print(f"[COCKPIT] Connecting to deployment {dep_id}…")
        from matrix_gui.core.event_bus import EventBus
        EventBus.emit("session.open.requested", dep_id, meta, self.vault_data)
