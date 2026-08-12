# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time, uuid, json, random, re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QTextEdit, QFileDialog, QComboBox
)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class InjectAgentDialog(QDialog):
    def __init__(self, session_id, bus, conn, deployment=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧬 Inject Agent")
        self.resize(580, 400)
        self.conn = conn
        self.session_id = session_id
        self.bus = bus
        self.agent_id = None
        self.deployment = deployment or {}
        self.selected_agent = None


        layout = QVBoxLayout(self)

        # === Vault selection combo ===
        self.vault_combo = QComboBox()
        self.vault_combo.addItem("— Select from Vault —")
        agents = self._extract_vault_agents()
        for label, node in agents.items():
            self.vault_combo.addItem(label, userData=node)
        self.vault_combo.currentIndexChanged.connect(self._on_vault_selected)
        layout.addWidget(self.vault_combo)

        # === Buttons for source options ===
        src_row = QHBoxLayout()
        btn_load_file = QPushButton("📁 Load from File")
        btn_load_file.clicked.connect(self._load_from_file)
        btn_clear = QPushButton("🧹 Clear")
        btn_clear.clicked.connect(self._clear_text)
        src_row.addWidget(btn_load_file)
        src_row.addWidget(btn_clear)
        layout.addLayout(src_row)

        # === JSON editor ===
        layout.addWidget(QLabel("Agent JSON (single node or list):"))
        self.agent_json = QTextEdit()
        layout.addWidget(self.agent_json)

        # === Action buttons ===
        row2 = QHBoxLayout()
        btn_ok = QPushButton("🚀 Inject")
        btn_ok.clicked.connect(self.deploy)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row2.addWidget(btn_ok)
        row2.addWidget(btn_cancel)
        layout.addLayout(row2)

    # ---------------------------------------------------------
    def _extract_vault_agents(self):
        """Extract agents from vault/deployment for dropdown."""
        result = {}
        try:
            agents = (self.deployment or {}).get("agents", [])
            for a in agents:
                uid = a.get("universal_id", "?")
                label = f"{a.get('name','?')} ({uid})"
                result[label] = a
        except Exception as e:
            emit_gui_exception_log("InjectAgentDialog._extract_vault_agents", e)
        return result

    def _get_selected_parent_uid(self):
        try:
            idx = self.vault_combo.currentIndex()
            data = self.vault_combo.itemData(idx)
            if isinstance(data, dict):
                return data.get("universal_id") or ""
            return ""
        except Exception as e:
            emit_gui_exception_log("InjectAgentDialog._get_selected_parent_uid", e)

    def _on_vault_selected(self, index):
        """Auto-fill JSON box when an agent is picked from vault."""
        if index <= 0:
            return
        agent = self.vault_combo.itemData(index)
        if not agent:
            return
        try:
            text = json.dumps(agent, indent=2)
            self.agent_json.setPlainText(text)
            self.selected_agent = agent
        except Exception as e:
            emit_gui_exception_log("InjectAgentDialog._on_vault_selected", e)

    def _load_from_file(self):
        """Load agent definition from a .json or .agent file."""
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Agent JSON", "", "Agent Files (*.json *.agent);;All Files (*)"
            )
            if not path:
                return
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # validate json
            json.loads(content)
            self.agent_json.setPlainText(content)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load file: {e}")
            emit_gui_exception_log("InjectAgentDialog._load_from_file", e)

    def _clear_text(self):
        self.agent_json.clear()
        self.vault_combo.setCurrentIndex(0)
        self.selected_agent = None


    # ---------------------------------------------------------
    def preselect_parent(self, uid):
        """Highlight the given parent agent in the dropdown."""
        for i in range(self.vault_combo.count()):
            data = self.vault_combo.itemData(i)
            if isinstance(data, dict) and data.get("universal_id") == uid:
                self.vault_combo.setCurrentIndex(i)
                break

    def deploy(self):
        self.agent_id = self._get_selected_parent_uid()
        if not self.agent_id:
            QMessageBox.warning(self, "Error", "Select a valid parent agent from the dropdown.")
            return

        try:
            agent_raw = self.agent_json.toPlainText().strip()
            if not agent_raw:
                QMessageBox.warning(self, "Error", "Agent JSON cannot be empty.")
                return

            # Parse JSON
            try:
                parsed_agent = json.loads(agent_raw)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Invalid JSON: {e}")
                return

            # Ensure proper structure
            if isinstance(parsed_agent, str):
                QMessageBox.warning(
                    self,
                    "Error",
                    "Top-level JSON cannot be a quoted string. "
                    "Remove extra quotes and try again."
                )
                return

            if isinstance(parsed_agent, dict):
                subtree = [parsed_agent]  # wrap single node
            elif isinstance(parsed_agent, list):
                if not all(isinstance(a, dict) for a in parsed_agent):
                    QMessageBox.warning(self, "Error", "List elements must be dictionaries.")
                    return
                subtree = parsed_agent
            else:
                QMessageBox.warning(self, "Error", "Agent JSON must be a dict or list of dicts.")
                return

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Invalid agent JSON: {e}")
            return

        # --- Confirmation ---
        count = len(subtree) if isinstance(subtree, list) else 1
        confirm = QMessageBox.question(
            self,
            "Confirm Injection",
            f"Inject {count} agent(s) under '{self.agent_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            # Append random suffixes
            def _rand_suffix():
                return ''.join(random.choices('0123456789', k=7))

            for a in subtree:
                uid = a.get("universal_id", "")
                if not re.search(r"_\d{6,7}$", uid):
                    suffix = _rand_suffix()
                    base = uid or a.get("name", "agent")
                    a["universal_id"] = f"{base}_{suffix}"

            # Build packet
            packet = Packet()
            packet.set_data({
                "handler": "cmd_inject_agents",
                "content": {
                    "target_universal_id": self.agent_id,
                    "subtree": subtree if len(subtree) > 1 else subtree[0],
                    "confirm_response": True,
                    "session_id": self.session_id,
                    "token": str(uuid.uuid4()),
                    "return_handler": "inject_dialog.result"
                },
                "ts": time.time()
            })

            # Fire it off
            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=packet
            )
            self.accept()

        except Exception as e:
            emit_gui_exception_log("InjectAgentDialog.deploy", e)
            QMessageBox.warning(self, "Error", f"Injection failed: {e}")
