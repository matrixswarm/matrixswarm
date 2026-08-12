from PyQt6.QtWidgets import QLabel, QComboBox, QPushButton, QVBoxLayout, QHBoxLayout, QDialog
from matrix_gui.modules.directive.maps.base import CERT_INJECTION_MAP
from PyQt6.QtCore import QTimer
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
            subtype = wrapper.get_connection_subtype()

            if not proto:
                continue  # skip non-connection consumers

            row = QHBoxLayout()
            row.addWidget(QLabel(f"{uid} ({proto})"))

            cb = QComboBox()
            status_lbl = QLabel("❌ unresolved")

            try:
                available = self._conn_mgr.get(proto, {}) or {}
                matched_any = False

                for conn_id, conn_data in available.items():
                    if proto == "email":
                        conn_type = str(conn_data.get("type", "")).lower().strip()
                        if subtype and conn_type != subtype:
                            continue

                    label = conn_data.get("label", conn_id)
                    if proto == "email":
                        label += f" ({conn_data.get('type', '?')})"
                    cb.addItem(label, (proto, conn_id))
                    matched_any = True

                if not matched_any:
                    cb.addItem("(no matching connections)", userData=None)

            except Exception as e:
                print(f"[ERROR] Failed to populate connection options for {uid} ({proto}): {e}")
                cb.addItem("(error loading connections)", userData=None)

            cb.currentIndexChanged.connect(
                lambda _, w=wrapper, c=cb, l=status_lbl: self._check_row(w, c, l)
            )
            row.addWidget(cb)
            row.addWidget(status_lbl)
            layout.addLayout(row)

            self._rows.append((wrapper, cb, status_lbl))
            self._check_row(wrapper, cb, status_lbl)
            had_any_rows = True

        # ---------------------------------------------------------------
        # if there were zero dropdown rows created, skip the dialog
        # (means no agent required connection assignment at all)
        # ---------------------------------------------------------------
        if not self._rows:
            print("[DEPLOY] No agents require connection resolution — skipping dialog.")
            QTimer.singleShot(0, self.accept)
            return
        # ---------------------------------------------------------------


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

        ok = False
        why = "unknown proto"

        # Map-driven check
        connection_map = CERT_INJECTION_MAP.get("connection", {})
        subtype = wrapper.get_connection_subtype()

        if proto == "email":
            required_fields = []
            if subtype in connection_map[proto]:
                required_fields = connection_map[proto][subtype].get("fields", [])
            else:
                # fallback: if unknown subtype, try to check both sets
                outgoing = connection_map[proto].get("outgoing", {}).get("fields", [])
                incoming = connection_map[proto].get("incoming", {}).get("fields", [])
                required_fields = list(set(outgoing + incoming))
        else:
            required_fields = connection_map[proto].get("fields", [])

        ok = all(conn.get(f) for f in required_fields) if required_fields else False
        why = "ok" if ok else f"missing required: {', '.join(required_fields)}"

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
        for wrapper, cb, _ in self._rows:
            data = cb.currentData()
            if not data:
                continue
            proto, conn_id = data
            connection = (self._conn_mgr.get(proto, {}) or {}).get(conn_id, {})
            if connection:
                wrapper.accept_connection(connection)

                # Attach a clean structured dict to the agent
                wrapper.agent.add_item("connection_info", {
                    "proto": proto,
                    "vault_ref": conn_id,  # link back to connection manager
                    "details": {
                        k: v for k, v in connection.items() if k not in ("proto",)
                    }
                })