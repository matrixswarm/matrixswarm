# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Main window for the graph editor
import json
import uuid

from pathlib import Path
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QWidget,
    QGraphicsScene, QGraphicsView, QMessageBox, QSplitter, QDialog
)
from PyQt6.QtCore import Qt
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from .workspace_loader import load_workspace
from .agent_palette import AgentPalette
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
            self.workspace_data = workspace_data
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

            self.palette = AgentPalette()
            right_layout.addWidget(self.palette)
            right_panel.setMinimumWidth(200)

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
                load_workspace(self.scene, agents_root, workspace_data)
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

    def save(self):
        nodes = collect_scene_nodes(self.scene)

        if not self.workspace_id:
            # brand new workspace
            self.workspace_id = str(uuid.uuid4())
            label = "New Workspace"
        else:
            label = self.workspace_data.get("label", "Unnamed Workspace")

        ws_uuid = self.workspace_id

        entry = {
            "uuid": ws_uuid,
            "label": label,
            "data": nodes
        }

        # --- Live Vault Path ---
        vcs = VaultCoreSingleton.get()
        workspaces = vcs.data.setdefault("workspaces", {})
        workspaces[self.workspace_id] = entry


        # persist to vault
        vcs.patch("workspaces", workspaces)

        #QMessageBox.information(self, "Saved", f"Workspace saved under {ws_uuid[:8]}")

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
        try:
            self.save()
        except Exception as e:
            print(f"[WORKSPACE] Close save failed: {e}")
        event.accept()

