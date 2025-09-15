import os, base64, hashlib, time, re, ast, json, ast
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton, QFileDialog,
    QCheckBox, QMessageBox
)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class ReplaceAgentDialog(QDialog):
    def __init__(self, session_id, bus, parent=None):
        super().__init__(parent)
        self.setWindowTitle("♻️ Replace Agent Source")
        self.resize(600, 500)

        self.session_id = session_id
        self.bus = bus
        self.file_path = None
        self.meta = {}

        layout = QVBoxLayout(self)

        # File picker
        self.file_label = QLabel("No file selected")
        btn_pick = QPushButton("📂 Select .py Source")
        btn_pick.clicked.connect(self.pick_file)

        row1 = QHBoxLayout()
        row1.addWidget(self.file_label)
        row1.addWidget(btn_pick)
        layout.addLayout(row1)

        # Name field
        layout.addWidget(QLabel("Agent Name"))
        self.name_edit = QLineEdit()
        layout.addWidget(self.name_edit)

        # Roles
        layout.addWidget(QLabel("Roles (comma separated)"))
        self.roles_edit = QLineEdit()
        layout.addWidget(self.roles_edit)

        # Config defaults
        layout.addWidget(QLabel("Config Defaults (JSON)"))
        self.config_edit = QTextEdit()
        self.config_edit.setPlaceholderText("{\n  \"check_interval_sec\": 10\n}")
        layout.addWidget(self.config_edit)

        # Operation toggles
        self.chk_update_tree = QCheckBox("Update Tree")
        self.chk_update_source = QCheckBox("Update Source")
        self.chk_restart = QCheckBox("Restart Agent")
        self.chk_update_source.setChecked(True)
        layout.addWidget(self.chk_update_tree)
        layout.addWidget(self.chk_update_source)
        layout.addWidget(self.chk_restart)

        # Buttons
        row2 = QHBoxLayout()
        btn_ok = QPushButton("Deploy")
        btn_ok.clicked.connect(self.deploy)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row2.addWidget(btn_ok)
        row2.addWidget(btn_cancel)
        layout.addLayout(row2)

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Agent Source", "", "Python (*.py)"
        )
        if not path:
            return
        self.file_path = path
        self.file_label.setText(os.path.basename(path))
        self.parse_meta(path)

    import ast
    from PyQt5.QtWidgets import QMessageBox

    def parse_meta(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()

            # Parse file into AST
            tree = ast.parse(code, filename=path)

            meta_dict = None
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "__AGENT_META__":
                            # Evaluate only safe literals
                            meta_dict = ast.literal_eval(node.value)
                            break
                if meta_dict is not None:
                    break

            if not meta_dict:
                self.meta = {
                    "name": os.path.splitext(os.path.basename(path))[0],
                    "roles": [],
                    "config_defaults": {}
                }
            else:
                self.meta = meta_dict

            # Populate dialog fields
            self.name_edit.setText(self.meta.get("name", ""))
            self.roles_edit.setText(",".join(self.meta.get("roles", [])))
            config_str = json.dumps(self.meta.get("config_defaults", {}), indent=2)
            self.config_edit.setPlainText(config_str)

        except Exception as e:
            QMessageBox.warning(self, "Parse Error", f"Could not parse metadata: {e}")


    def deploy(self):
        if not self.file_path:
            QMessageBox.warning(self, "No File", "Select a source file first.")
            return

        try:
            # Update meta from fields
            roles = [r.strip() for r in self.roles_edit.text().split(",") if r.strip()]
            config = {}
            if self.config_edit.toPlainText().strip():
                config = json.loads(self.config_edit.toPlainText())

            self.meta.update({
                "name": self.name_edit.text().strip(),
                "roles": roles,
                "config_defaults": config
            })

            with open(self.file_path, "rb") as f:
                code = f.read()
                encoded = base64.b64encode(code).decode("utf-8")
                file_hash = hashlib.sha256(code).hexdigest()

            payload = {
                "handler": "cmd_replace_source",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": self.meta["name"],  # use name as UID fallback
                    "source_payload": {
                        "payload": encoded,
                        "sha256": file_hash
                    },
                    "meta": self.meta,
                    "update_tree": self.chk_update_tree.isChecked(),
                    "update_source": self.chk_update_source.isChecked(),
                    "restart": self.chk_restart.isChecked()
                }
            }

            pk = Packet()
            pk.set_data(payload)
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk)

            QMessageBox.information(self, "Deployed",
                f"Agent {self.meta['name']} replaced.\nSHA256: {file_hash[:12]}…")
            self.accept()

        except Exception as e:
            emit_gui_exception_log("ReplaceAgentDialog.deploy", e)
            QMessageBox.warning(self, "Error", f"Deployment failed: {e}")
