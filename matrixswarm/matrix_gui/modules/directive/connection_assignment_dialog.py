from PyQt5.QtWidgets import QDialog, QLabel, QComboBox, QPushButton, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore import Qt


class ConnectionAssignmentDialog(QDialog):
    def __init__(self, parent, wrapped_agents, conn_mgr):
        super().__init__(parent)
        self.setWindowTitle("Connection Assignment")
        self._conn_mgr = conn_mgr
        self._rows = []

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        had_any_rows = False

        for w in wrapped_agents:
            print(f"{w.get_universal_id()} → {w.get_requested_proto()}")

        for wrapper in wrapped_agents:
            uid = wrapper.get_universal_id()
            proto = wrapper.get_requested_proto()
            if not proto:
                continue  # skip non-connection consumers

            row = QHBoxLayout()
            row.addWidget(QLabel(f"{uid} ({proto})"))

            cb = QComboBox()
            status_lbl = QLabel("❌ unresolved")

            for conn_id, conn_data in conn_mgr.get(proto, {}).items():
                cb.addItem(conn_id, (proto, conn_id))

            cb.currentIndexChanged.connect(
                lambda _, w=wrapper, c=cb, l=status_lbl: self._check_row(w, c, l)
            )
            row.addWidget(cb)
            row.addWidget(status_lbl)
            layout.addLayout(row)

            self._rows.append((wrapper, cb, status_lbl))
            self._check_row(wrapper, cb, status_lbl)
            had_any_rows = True

        # Always build buttons
        btn_row = QHBoxLayout()
        self._ok = QPushButton("OK")
        self._ok.setEnabled(had_any_rows)
        self._ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._ok)
        btn_row.addWidget(cancel)
        layout.addLayout(btn_row)

    def _check_row(self, wrapper, cb, lbl):
        data = cb.currentData()
        if not data:
            lbl.setText("❌ unresolved")
            lbl.setToolTip("No connection selected")
            self._update_ok_enabled()
            return

        proto, conn_id = data
        conn = (self._conn_mgr.get(proto, {}) or {}).get(conn_id, {})
        host = conn.get("host")
        port = conn.get("port")

        if proto in ("https", "wss"):
            ok = bool(host and port)
            why = "ok" if ok else "missing host or port"
        elif proto == "discord":
            ok = bool(conn.get("channel_id"))
            why = "channel_id required"
        elif proto == "telegram":
            ok = bool(conn.get("chat_id"))
            why = "chat_id required"
        elif proto == "email":
            ok = bool(conn.get("smtp_server"))
            why = "smtp_server required"
        elif proto == "slack":
            ok = bool(conn.get("webhook_url"))
            why = "webhook_url required"
        else:
            ok = False
            why = "unknown proto"

        lbl.setText("✅ resolved" if ok else "❌ unresolved")
        lbl.setToolTip(f"{proto}: {why}")
        self._update_ok_enabled()

    def _update_ok_enabled(self):
        if not hasattr(self, "_ok"):
            return

        all_resolved = all(
            cb.currentData() is not None and lbl.text().startswith("✅")
            for _, cb, lbl in self._rows
        )

        self._ok.setEnabled(all_resolved)
        if not all_resolved:
            self._ok.setToolTip("All agents must be resolved before proceeding")
        else:
            self._ok.setToolTip("")

    def assignments(self):
        return {
            wrapper.get_universal_id(): cb.currentData()
            for wrapper, cb, _ in self._rows
            if cb.currentData()
        }

    def apply_assignments(self):
        """Apply selected connections directly to each wrapped agent."""
        for wrapper, cb, _ in self._rows:
            data = cb.currentData()
            if not data:
                continue
            proto, conn_id = data
            connection = (self._conn_mgr.get(proto, {}) or {}).get(conn_id, {})
            if connection:
                wrapper.accept_connection(connection)