from PyQt5 import QtWidgets
from matrix_gui.modules.net.edit_connection_dialog import edit_connection_dialog
from matrix_gui.core.event_bus import EventBus

class ConnectionManagerDialog(QtWidgets.QDialog):
    def __init__(self, vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.setWindowTitle("Connection Manager")
        self.setMinimumSize(900, 480)

        # Tabs for each protocol
        self.tabs = QtWidgets.QTabWidget()

        # Track tables by proto
        self.tables = {}
        for proto in ["https", "wss", "discord", "telegram", "openai", "email", "slack"]:
            table = QtWidgets.QTableWidget()
            table.setColumnCount(6)
            table.setHorizontalHeaderLabels(
                ["Label", "Host / Target", "Port / Channel", "Default Channel", "Used In", "Serial"]
            )
            table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.tables[proto] = table
            self.tabs.addTab(table, proto.upper())

        # Buttons
        self.btn_add = QtWidgets.QPushButton("Add")
        self.btn_edit = QtWidgets.QPushButton("Edit")
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_close = QtWidgets.QPushButton("Close")

        self.btn_add.clicked.connect(self.add_entry)
        self.btn_edit.clicked.connect(self.edit_selected)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_close.clicked.connect(self.accept)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.btn_add)
        button_row.addWidget(self.btn_edit)
        button_row.addWidget(self.btn_delete)
        button_row.addStretch()
        button_row.addWidget(self.btn_close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addLayout(button_row)

        self.reload_all()

    def showEvent(self, event):
        super().showEvent(event)
        self.reload_all()

    def get_connection_manager(self):
        return self.vault.setdefault("connection_manager", {})

    def reload_all(self):
        """Reload all protocol tables"""
        for proto in self.tables:
            self.load_table(proto)

    def load_table(self, proto):
        cm = self.get_connection_manager().get(proto, {})
        table = self.tables[proto]
        table.setRowCount(0)

        for conn_id, data in cm.items():
            row = table.rowCount()
            table.insertRow(row)

            # Label
            label = data.get("label", conn_id)
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(label)))
            # Host / Target
            host_or_target = data.get("host") or data.get("channel_id") or ""
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(host_or_target)))
            # Port / Channel
            port_or_channel = data.get("port") or data.get("chat_id") or data.get("api_key", "")[:6] + "…" or ""
            table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(port_or_channel)))
            # Default Channel
            table.setItem(row, 3, QtWidgets.QTableWidgetItem(str(data.get("default_channel", ""))))
            # Used In
            table.setItem(row, 4, QtWidgets.QTableWidgetItem(", ".join(self.find_usage(conn_id))))
            # Serial
            table.setItem(row, 5, QtWidgets.QTableWidgetItem(str(data.get("serial", ""))))

    def current_proto_and_table(self):
        idx = self.tabs.currentIndex()
        proto = self.tabs.tabText(idx).lower()
        return proto, self.tables[proto]

    def find_usage(self, conn_id):
        used = []
        deployments = self.vault.get("deployments", {})
        for dep_id, dep in deployments.items():
            if not isinstance(dep, dict):
                continue
            for agent in dep.get("agents", []):
                for tag in agent.get("tags", []):
                    ct = tag.get("connection-tag")
                    if ct and ct.get("id") == conn_id:
                        used.append(dep_id)
        return used

    def add_entry(self):
        proto, _ = self.current_proto_and_table()
        conn_id, data = edit_connection_dialog(self, default_proto=proto, data={})
        if conn_id:
            new_proto = data.get("proto", proto)
            cm_all = self.get_connection_manager()
            cm_all.setdefault(new_proto, {})[conn_id] = data
            self.load_table(new_proto)
            EventBus.emit("vault.save.requested")

    def edit_selected(self):
        proto, table = self.current_proto_and_table()
        row = table.currentRow()
        if row < 0:
            return

        item = table.item(row, 0)
        if not item:
            return  # nothing selected or row not populated
        label = item.text()
        conn_id = self.find_conn_id_by_label(proto, label)
        cm_all = self.get_connection_manager()
        cm_old = cm_all.get(proto, {})
        if conn_id not in cm_old:
            return

        existing = cm_old[conn_id]
        conn_id_new, data = edit_connection_dialog(
            self, default_proto=existing.get("proto", proto),
            data=existing, conn_id=conn_id
        )
        if not conn_id_new:
            return

        new_proto = data["proto"]
        if new_proto != proto:
            cm_old.pop(conn_id)
            cm_all.setdefault(new_proto, {})[conn_id_new] = data
        else:
            if conn_id_new != conn_id:
                cm_old.pop(conn_id)
            cm_old[conn_id_new] = data

        EventBus.emit("vault.save.requested")
        self.reload_all()

    def delete_selected(self):
        proto, table = self.current_proto_and_table()
        row = table.currentRow()
        if row < 0:
            return
        label = table.item(row, 0).text()
        conn_id = self.find_conn_id_by_label(proto, label)
        if not conn_id:
            return
        used = self.find_usage(conn_id)
        if used:
            QtWidgets.QMessageBox.warning(
                self, "Used Connection",
                f"This connection is used in: {', '.join(used)}\n\n"
                f"Deleting it won't break existing deployments, but you can't reassign it later."
            )
        confirm = QtWidgets.QMessageBox.question(
            self, "Confirm Delete",
            f"Delete connection '{conn_id}'?"
        )
        if confirm == QtWidgets.QMessageBox.Yes:
            self.get_connection_manager()[proto].pop(conn_id, None)
            self.load_table(proto)
            EventBus.emit("vault.save.requested")

    def find_conn_id_by_label(self, proto, label):
        cm = self.get_connection_manager().get(proto, {})
        for cid, data in cm.items():
            if data.get("label") == label or cid == label:
                return cid
        return None
