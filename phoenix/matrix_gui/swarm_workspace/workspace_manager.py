# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition Workspace Manager
# Gemini, code enhancements: clone workspace feature added 20260114
import uuid
import json
import copy
from pathlib import Path
from matrix_gui.core.event_bus import EventBus
from PyQt6.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout,
    QPushButton, QMessageBox, QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from .cls_lib.agent.agent_node import AgentNode

class WorkspaceManagerDialog(QDialog):
    workspace_selected = pyqtSignal(str)
    def __init__(self):

        super().__init__()

        self.setWindowTitle("Swarm Workspaces")

        vcs = VaultCoreSingleton.get()
        self.vcs = vcs
        self.vault_data = vcs.data
        self.vault_data.setdefault("workspaces", {})
        vcs.patch("workspaces", self.vault_data["workspaces"])

        self.workspaces = self.vault_data["workspaces"]

        # UI
        layout = QVBoxLayout(self)
        self.ws_list = QListWidget()
        layout.addWidget(self.ws_list)

        btns = QHBoxLayout()
        self.new_btn = QPushButton("🆕 New")
        self.open_btn = QPushButton("📂 Open")
        self.clone_btn = QPushButton("👯 Clone")
        self.rename_btn = QPushButton("✏️ Rename")
        self.delete_btn = QPushButton("🗑 Delete")

        btns.addWidget(self.new_btn)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.clone_btn)
        btns.addWidget(self.rename_btn)
        btns.addWidget(self.delete_btn)
        layout.addLayout(btns)

        self._populate()

        # Signals
        self.new_btn.clicked.connect(self._new_workspace)
        self.open_btn.clicked.connect(self._open_workspace)
        self.clone_btn.clicked.connect(self._clone_workspace)
        self.rename_btn.clicked.connect(self._rename_workspace)
        self.delete_btn.clicked.connect(self._delete_workspace)
        self.ws_list.itemDoubleClicked.connect(self._open_workspace)

        self.selected_uuid = None

    # ------------------------------------------------------------------
    def _persist(self):
        """Persist workspace list to vault through VaultCore."""
        vcs = VaultCoreSingleton.get()  # live vault authority
        vcs.data["workspaces"] = self.workspaces  # write into live dict
        vcs.patch("workspaces", self.workspaces)  # validate + commit

    # ------------------------------------------------------------------
    def _populate(self):
        self.ws_list.clear()
        for uuid_, ws in self.workspaces.items():
            label = ws.get("label", "(unnamed)")
            item = QListWidgetItem(f"{uuid_[:8]} — {label}")
            item.setData(Qt.ItemDataRole.UserRole, uuid_)
            self.ws_list.addItem(item)

    # ------------------------------------------------------------------
    def _new_workspace(self):

        try:
            vcs = VaultCoreSingleton.get()

            # Commander fix — ensure section exists in vault
            vcs.data.setdefault("workspaces", {})
            self.workspaces = vcs.data["workspaces"]

            # Now safe to create the workspace
            ws_uuid = uuid.uuid4().hex

            self.workspaces[ws_uuid] = {
                "uuid": ws_uuid,
                "label": "Untitled Workspace",
                "data": []
            }

            # Load Matrix meta.json
            base_dir = Path(__file__).resolve().parents[2]  # matrix_gui/swarm_workspace
            agents_root = base_dir / "agents_meta"

            matrix_meta_path = agents_root / "matrix.json"
            if not matrix_meta_path.exists():
                raise RuntimeError(f"Matrix meta.json not found at: {matrix_meta_path}")

            # Load MATRIX meta
            matrix_meta = json.loads(matrix_meta_path.read_text(encoding="utf-8"))

            # Build proper AgentNode
            matrix_node = AgentNode(matrix_meta).get_node()
            matrix_node["parent"] = None

            # Inject into workspace
            self.workspaces[ws_uuid]["data"].append(matrix_node)

            # Persist
            self._persist()

            # return UUID to caller
            self.selected_uuid = ws_uuid
            self.workspace_selected.emit(ws_uuid)
            self._populate()

        except Exception as e:
            emit_gui_exception_log("WorkspaceManagerDialog._new_workspace", e)

    def _clone_workspace(self):
        """Creates a deep copy of the selected workspace with a new UUID."""
        try:
            item = self.ws_list.currentItem()
            if not item:
                QMessageBox.warning(self, "No Selection", "Select a workspace to clone.")
                return

            original_uuid = item.data(Qt.ItemDataRole.UserRole)
            original_ws = self.workspaces.get(original_uuid)

            if not original_ws:
                return

            # 1. Deep copy the data to ensure independence
            new_ws = copy.deepcopy(original_ws)

            # 2. Assign a new UUID and update the label
            new_uuid = uuid.uuid4().hex
            new_ws["uuid"] = new_uuid
            new_ws["label"] = f"Copy of {original_ws.get('label', 'Untitled')}"

            # 3. Insert into the vault dictionary
            self.workspaces[new_uuid] = new_ws

            # 4. Persist and Refresh
            self._persist()
            self._populate()

            # Select the new clone in the list
            for i in range(self.ws_list.count()):
                if self.ws_list.item(i).data(Qt.ItemDataRole.UserRole) == new_uuid:
                    self.ws_list.setCurrentRow(i)
                    break

        except Exception as e:
            emit_gui_exception_log("WorkspaceManagerDialog._clone_workspace", e)
            QMessageBox.critical(self, "Clone Error", f"Failed to clone: {e}")

    # ------------------------------------------------------------------
    def _open_workspace(self):
        try:
            item = self.ws_list.currentItem()
            if not item:
                return
            self.selected_uuid = item.data(Qt.ItemDataRole.UserRole)
            self.workspace_selected.emit(self.selected_uuid)
            # do NOT call self.accept()

        except Exception as e:
            emit_gui_exception_log("WorkspaceManagerDialog._open_workspace", e)

    # ------------------------------------------------------------------
    def _delete_workspace(self):
        try:
            item = self.ws_list.currentItem()
            if not item:
                QMessageBox.warning(self, "No Selection", "Select a workspace to delete.")
                return

            uuid_ = item.data(Qt.ItemDataRole.UserRole)
            label = self.workspaces.get(uuid_, {}).get("label", "(unnamed)")

            confirm = QMessageBox.question(
                self,
                "Delete Workspace",
                f"Are you sure you want to delete\n\n{label}\n({uuid_[:8]})?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

            # 1. remove from live dict
            if uuid_ in self.workspaces:
                del self.workspaces[uuid_]

            # 2. persist through VaultCore
            vcs = VaultCoreSingleton.get()
            vcs.patch("workspaces", self.workspaces)

            # 3. refresh UI
            self._populate()

        except Exception as e:
            emit_gui_exception_log("WorkspaceManagerDialog._delete_workspace", e)
            QMessageBox.critical(self, "Error", str(e))

    # ------------------------------------------------------------------
    def _rename_workspace(self):
        item = self.ws_list.currentItem()
        if not item:
            return

        uuid_ = item.data(Qt.ItemDataRole.UserRole)
        current = self.workspaces[uuid_].get("label", "")

        new_name, ok = QInputDialog.getText(self, "Rename Workspace", "New label:", text=current)

        if ok and new_name.strip():
            self.workspaces[uuid_]["label"] = new_name.strip()
            self._persist()
            self._populate()

