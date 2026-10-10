# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Main window for the graph editor
import json
import uuid
from copy import deepcopy
from PyQt6 import sip

from pathlib import Path
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QWidget,
    QGraphicsScene, QGraphicsView, QMessageBox, QSplitter, QDialog, QLabel
)
from PyQt6.QtCore import Qt, QTimer
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from .workspace_loader import load_workspace
from .agent_palette import AgentPalettePanel
from .panels.agent_inspector.agent_inspector import AgentInspector
from .workspace_serializer import collect_scene_nodes
from .workspace_validator import validate_workspace
from .cls_lib.graph.tree_graph_controller import TreeGraphController
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_resolver import ConstraintResolver
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.swarm_workspace.cls_lib.deployment.deploy_objects import (DeploymentSession, DeploymentViewer)

class SwarmWorkspaceDialog(QDialog):
    def __init__(self, agents_root, workspace_data=None):
        super().__init__()
        try:
            self.setWindowTitle("Swarm Workspace")
            self.setMinimumSize(1200, 700)
            self.workspace_data = deepcopy(workspace_data or {})
            self._vault_core = VaultCoreSingleton.get()
            self._saving = False
            self._pending_entry = None
            self._saved_entry = None
            self._close_requested = False
            self._allow_close = False
            self._write_slow = False
            self._ready_timer = QTimer(self)
            self._ready_timer.setSingleShot(True)
            self._ready_timer.setInterval(3000)
            self._ready_timer.timeout.connect(self._show_ready)
            self._slow_save_timer = QTimer(self)
            self._slow_save_timer.setSingleShot(True)
            self._slow_save_timer.setInterval(5000)
            self._slow_save_timer.timeout.connect(self._save_is_slow)
            self.agents_root = agents_root
            self.default_parent = None
            self.workspace_id = None

            if workspace_data:
                self.workspace_id = workspace_data.get("uuid")
            # --- top buttons
            top = QHBoxLayout()

            #self.validate_btn = QPushButton("Validate")
            self.deploy_btn = QPushButton("Deploy")
            #self.save_btn = QPushButton("Save Workspace")
            #top.addWidget(self.validate_btn)
            top.addStretch(1)
            top.addWidget(self.deploy_btn)

            splitter = QSplitter(Qt.Orientation.Horizontal)

            # === LEFT PANE: Inspector + Palette ===
            left_panel = QWidget()
            left_layout = QVBoxLayout(left_panel)
            left_layout.setContentsMargins(4, 4, 4, 4)
            left_layout.setSpacing(6)

            # RIGHT PANE: Agent Palette
            right_panel = QWidget()
            right_layout = QVBoxLayout(right_panel)
            right_layout.setContentsMargins(4, 4, 4, 4)
            right_layout.setSpacing(6)

            self.palette_panel = AgentPalettePanel(right_panel)
            self.palette = self.palette_panel.palette
            right_layout.addWidget(self.palette_panel)
            right_panel.setMinimumWidth(280)

            # Inspector gets a fixed minimum width
            self.inspector = AgentInspector(parent=self)
            self.inspector.setMinimumWidth(350)
            left_layout.addWidget(self.inspector, stretch=0)  # Inspector should NOT stretch


            splitter.setStretchFactor(0, 0)  # left side small
            splitter.setStretchFactor(1, 1)  # right side grows


            # === RIGHT PANE: Canvas ===
            self.scene = QGraphicsScene()
            self.view = QGraphicsView(self.scene)
            self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
            self.scene.workspace = self

            splitter.addWidget(left_panel)  # Inspector
            splitter.addWidget(self.view)  # Canvas
            splitter.addWidget(right_panel)  # Agent Palette

            # Give Inspector room
            left_panel.setMinimumWidth(200)

            # Make both panels behave rationally
            splitter.setStretchFactor(0, 0)  # Inspector
            splitter.setStretchFactor(1, 1)  # Canvas (expandable)
            splitter.setStretchFactor(2, 0)  # Palette stays fixed width


            # CREATE CONTROLLER NOW (before load)
            self.controller = TreeGraphController(self.scene, self.inspector)

            # Load workspace AFTER controller is ready
            if workspace_data and workspace_data.get("data"):
                load_workspace(self.scene, agents_root, self.workspace_data)
            else:
                print("[WORKSPACE] no saved agents to load")

            # Auto-select Matrix on load
            for item in self.controller.nodes.values():
                if item.node.get_name().lower() == "matrix":
                    item.setSelected(True)
                    item.setFocus()
                    self.inspector.load(item.node)
                    break


            # --- main layout ---
            layout = QVBoxLayout(self)
            layout.addLayout(top)
            layout.addWidget(splitter)
            status_row = QHBoxLayout()
            self.save_status = QLabel("Ready…")
            self.save_status.setAccessibleName("Workspace save status")
            self.retry_save_btn = QPushButton("Retry Save")
            self.retry_save_btn.setAutoDefault(False)
            self.retry_save_btn.hide()
            self.retry_save_btn.clicked.connect(self.save)
            status_row.addWidget(self.save_status, 1)
            status_row.addWidget(self.retry_save_btn)
            layout.addLayout(status_row)

            # drag/drop handlers
            self.view.setAcceptDrops(True)
            self.view.viewport().setAcceptDrops(True)
            self.view.dragEnterEvent = self.dragEnterEvent
            self.view.dragMoveEvent = self.dragMoveEvent
            self.view.dropEvent = self.dropEvent

            # connect buttons
            #self.validate_btn.clicked.connect(self.validate)
            self.deploy_btn.clicked.connect(self.on_deploy_clicked)
            self.deploy_btn.setAutoDefault(False)
            self.deploy_btn.setDefault(False)

        except Exception as e:
            emit_gui_exception_log("SwarmWorkspaceDialog.__init__", e)

    def dragEnterEvent(self, event):
        event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        try:
            agent_name = event.mimeData().text().strip()

            # Load meta
            base = Path(__file__).resolve().parents[2] / "agents_meta"
            meta_path = base / f"{agent_name}.json"
            if not meta_path.exists():
                print(f"[DROP] ❌ No meta.json for {agent_name}")
                return

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            # Map to scene coordinates
            drop_pos = self.view.mapToScene(event.position().toPoint())

            # Let controller handle everything
            item = self.controller.add_agent(meta, drop_pos, self.view)
            if item:
                self.save()

        except Exception as e:
            emit_gui_exception_log("SwarmWorkspaceDialog.dropEvent", e)

    def select_node(self, item):
        self.selected_item = item
        self.default_parent = item.node["name"]

    def validate(self):
        errors = validate_workspace([obj for obj in self.scene.items() if hasattr(obj, "node")])
        if errors:
            QMessageBox.warning(self, "Validation Failed", "\n".join(errors))
        else:
            QMessageBox.information(self, "Ok", "Workspace is valid!")

    def _snapshot_entry(self):
        if not self.workspace_id:
            self.workspace_id = str(uuid.uuid4())
        return deepcopy({"uuid": self.workspace_id,
                         "label": self.workspace_data.get("label", "New Workspace"),
                         "data": collect_scene_nodes(self.scene)})

    def save(self):
        """Accept an autosave request, not a claim that disk is already saved."""
        try:
            if self._vault_core is not VaultCoreSingleton.get() or self._vault_core._closed:
                raise RuntimeError("Workspace belongs to an inactive vault; reopen it from the current vault")
            entry = self._snapshot_entry()
            self._pending_entry = entry
            if self._saving:
                if self._write_slow:
                    self._save_is_slow()
                else:
                    self.save_status.setText("Trying to write to vault… newer updates pending")
                return True
            if entry == self._saved_entry:
                self._pending_entry = None
                return True
            self._saving = True
            self._ready_timer.stop()
            self._write_slow = False
            self._pending_entry = None
            self.retry_save_btn.hide()
            self.save_status.setText("Trying to write to vault…")
            self._slow_save_timer.start()
            self._vault_core.save_workspace_async(
                entry, lambda success: self._save_completed(entry, success))
            return True
        except Exception as e:
            emit_gui_exception_log("SwarmWorkspaceDialog.save", e)
            self._save_failed()
            return False

    def _save_failed(self):
        self._ready_timer.stop()
        self._slow_save_timer.stop()
        self._saving = False
        self._close_requested = False
        self.save_status.setText("Save failed — changes retained in editor; retry before closing")
        self.retry_save_btn.show()

    def _save_is_slow(self):
        if self._saving:
            self._write_slow = True
            self.save_status.setText("Still trying to write to vault — please pause edits until this clears")

    def _show_ready(self):
        if not self._saving and self._pending_entry is None:
            self.save_status.setText("Ready…")

    def _save_completed(self, entry, success):
        if sip.isdeleted(self):
            return
        if self._vault_core is not VaultCoreSingleton.get() or self._vault_core._closed:
            self._save_failed()
            self.save_status.setText("Vault closed or changed — reopen this workspace before saving")
            return
        self._slow_save_timer.stop()
        self._saving = False
        if not success:
            self._save_failed()
            return
        self._saved_entry = deepcopy(entry)
        # Never replace the live editor with an older completed snapshot.
        try:
            if self._snapshot_entry() != entry:
                self.save()
                return
        except Exception:
            self._save_failed()
            return
        self._pending_entry = None
        self.save_status.setText("Saved to Vault ✓")
        self._ready_timer.start()
        if self._close_requested:
            self._allow_close = True
            self.close()

    def on_deploy_clicked(self):
        tree, root_uid = self.controller.export_agent_tree()

        resolver = ConstraintResolver()  # or ConstraintResolver if renamed
        session = DeploymentSession(self, tree, root_uid, resolver)

        builder = session.run(self.workspace_id)
        if not builder:
            QMessageBox.critical(
                self,
                "Deployment Blocked",
                "Deployment was stopped due to missing required constraints.\n\n"
                "Check the Agent Inspector for highlighted errors."
            )
            return

        #dlg = DeploymentViewer(builder, self)
        #dlg.exec()


    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
            return
        try:
            if not self._saving and self._snapshot_entry() == self._saved_entry:
                event.accept()
                return
        except Exception:
            self._save_failed()
            event.ignore()
            return
        event.ignore()
        self._close_requested = True
        self.save()

    def reject(self):
        # Escape must obey the same persistence rule as the title-bar close.
        if self._allow_close:
            super().reject()
        else:
            self.close()

