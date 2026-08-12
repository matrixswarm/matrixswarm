# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Works with RegistryManager, ConstraintRowWidget, WorkspaceBus
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QScrollArea
)
from PyQt6.QtCore import Qt
from matrix_gui.registry.registry_manager import RegistryManagerDialog
from matrix_gui.swarm_workspace.panels.constraints.constraint_row_widget import ConstraintRowWidget
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.registry.object_classes import EDITOR_REGISTRY, PROVIDER_REGISTRY
from .uid_line_edit import UIDLineEdit
class AgentInspector(QWidget):
    """
    Commander Edition — Unified Agent Inspector
    Now includes:
      • Name, UID, Parent dropdown, Connections
      • FULL Constraint Box with per-row widgets
      • Required constraints locked
      • Auto constraints stripped down
      • Add Constraint = open registry directly
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.node = None
        self.workspace = parent   # SwarmWorkspaceDialog reference

        main = QVBoxLayout(self)
        main.setContentsMargins(4, 4, 4, 4)
        main.setSpacing(8)

        # HEADER
        title = QLabel("<b>Agent Inspector</b>")
        main.addWidget(title)

        # AGENT NAME (runtime)
        self.name_edit = QLineEdit()
        self.name_edit.setReadOnly(True)
        self.name_edit.setStyleSheet("color:#fff; font-weight:bold;")
        main.addWidget(QLabel("Source Filename"))
        main.addWidget(self.name_edit)


        # UID (read-only)
        self.uid_edit =  UIDLineEdit(self._validate_uid)
        self.uid_edit.setReadOnly(False)
        self.uid_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        #universal_id
        main.addWidget(QLabel("Universal ID"))
        main.addWidget(self.uid_edit)

        # CONSTRAINT SECTION HEADER
        main.addWidget(QLabel("<b>Requirements</b>"))

        # CONSTRAINT SCROLL AREA
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.constraint_panel = QWidget()
        self.constraint_layout = QVBoxLayout(self.constraint_panel)
        self.constraint_layout.setContentsMargins(2, 2, 2, 2)
        self.constraint_layout.setSpacing(4)
        scroll.setWidget(self.constraint_panel)
        main.addWidget(scroll, 1)

        # CONTROL BUTTONS FOR CONSTRAINTS
        #button_row = QHBoxLayout()
        #self.btn_assign = QPushButton("Assign")
        #self.btn_edit = QPushButton("Edit")
        #self.btn_remove = QPushButton("Remove")
        #button_row.addWidget(self.btn_assign)
        #button_row.addWidget(self.btn_edit)
        #button_row.addWidget(self.btn_remove)
        #button_row.addStretch()
        #main.addLayout(button_row)

        # ADD CONSTRAINT BUTTON
        #self.btn_add_constraint = QPushButton("+ Add Requirement")
        #main.addWidget(self.btn_add_constraint)

        # Connections
        #self.btn_assign.clicked.connect(self._assign_selected)
        #self.btn_edit.clicked.connect(self._edit_selected)
        #self.btn_remove.clicked.connect(self._remove_selected)
        #self.btn_add_constraint.clicked.connect(self._add_constraint)

        #self.deploy_btn.setAutoDefault(False)
        #self.deploy_btn.setDefault(False)


        scroll.setMinimumHeight(230)
        scroll.setMaximumHeight(400)

    # ------------------------------------------------------------
    # LOAD THE AGENT
    # ------------------------------------------------------------
    def load(self, node, class_list=None):
        """Load AgentNode into inspector."""


        self.node = node
        # === META (SOURCE) + RUNTIME NAME ===
        self.name_edit.setText(node.get_name())

        # --- Commander Patch: Parent + UID Debug Fields ---
        parent_gid = None
        if hasattr(node, "get_parent"):
            parent_gid = node.get_parent()
        elif isinstance(node, dict):
            parent_gid = node.get("parent")

        # Remove old debug labels if they exist
        if hasattr(self, "debug_labels"):
            for lbl in self.debug_labels:
                self.layout().removeWidget(lbl)
                lbl.deleteLater()

        self.debug_labels = []

        chld_parent = QLabel(f"Graph ID: {node.get_graph_id() or '(none)'}")
        chld_parent.setStyleSheet("color:#ccc; font-size:11px;")

        # Create clean debug display
        lbl_parent = QLabel(f"Parent Graph ID: {parent_gid or '(none)'}")
        lbl_parent.setStyleSheet("color:#ccc; font-size:11px;")

        self.layout().insertWidget(3, chld_parent)
        self.layout().insertWidget(4, lbl_parent)

        self.debug_labels.extend([chld_parent, lbl_parent])

        # Normal fields

        uid = node.get_universal_id()
        self.uid_edit.setText(uid)

        # Matrix UID is locked
        is_matrix = node.get_name().lower() == "matrix"
        self.uid_edit.setReadOnly(is_matrix)
        self.uid_edit.setEnabled(not is_matrix)

        self._reload_constraints()


    # ------------------------------------------------------------
    # CONSTRAINT RELOAD / RENDER
    # ------------------------------------------------------------
    def _reload_constraints(self):
        # Clear existing
        for i in reversed(range(self.constraint_layout.count())):
            widget = self.constraint_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        # Rebuild rows
        for c in self.node.get_constraints():
            row = ConstraintRowWidget(
                c,
                edit_callback=self._edit_constraint,
                remove_callback=self._remove_constraint,
                change_callback=self._reload_constraints
            )

            # REQUIRED / AUTO CLEANUP
            if c.get("required", False) or c.get("auto", False):
                # Remove button disabled/hidden
                if hasattr(row, "remove_btn"):
                    row.remove_btn.setEnabled(False)
                    row.remove_btn.hide()

                # Switch button disabled/hidden
                if hasattr(row, "switch_btn"):
                    row.switch_btn.setEnabled(False)
                    row.switch_btn.hide()

                # Auto constraints (system controlled) → hide edit too
                if c.get("auto", False) and hasattr(row, "edit_btn"):
                    row.edit_btn.setEnabled(False)
                    row.edit_btn.hide()

            self.constraint_layout.addWidget(row)

    # ------------------------------------------------------------
    # ASSIGN EXISTING ROW
    # ------------------------------------------------------------
    def _assign_selected(self):
        row = self._get_selected_constraint()
        if not row:
            return

        constraint = row

        cls = constraint["class"]

        def assign_callback(cls_name, serial):
            # CANCEL if user did not select anything
            if not cls_name or not serial:
                print("[Inspector] Assign canceled – no provider selected.")
                return

            constraint["serial"] = serial
            constraint["met"] = True
            self._reload_constraints()

        dlg = RegistryManagerDialog(
            parent=self,
            class_lock=cls,
            assign_callback=assign_callback
        )
        dlg.exec()

    # ------------------------------------------------------------
    # EDIT SELECTED ROW
    # ------------------------------------------------------------
    def _edit_constraint(self, constraint):
        # Handled in row widget; this delegate required only for refresh
        self._reload_constraints()

    def _edit_selected(self):
        row = self._get_selected_constraint()
        if not row:
            return
        self._edit_constraint(row)

    # ------------------------------------------------------------
    # REMOVE
    # ------------------------------------------------------------
    def _remove_constraint(self, constraint):
        # Backend check: do NOT remove required
        if constraint.get("required", False):
            print("[Inspector] Cannot remove REQUIRED constraint")
            return

        self.node.constraints.remove(constraint)
        self._reload_constraints()

    def _remove_selected(self):
        row = self._get_selected_constraint()
        if not row:
            return
        self._remove_constraint(row)

    # ------------------------------------------------------------
    # ADD CONSTRAINT → Direct Registry Popup
    # ------------------------------------------------------------
    def _add_constraint(self):
        # Determine first class available

        valid_classes = [
            cls for cls in EDITOR_REGISTRY.keys()
            if cls in PROVIDER_REGISTRY and PROVIDER_REGISTRY[cls] is not None
        ]

        if not valid_classes:
            print("[Inspector] No valid classes found with providers.")
            return

        first_class = valid_classes[0]

        def assign_callback(cls_name, serial):
            if not cls_name or not serial:
                print("[Inspector] Add canceled – no provider selected.")
                return

            new_constraint = {
                "class": cls_name,
                "raw": {},
                "serial": serial,
                "auto": False,
                "met": True,
                "required": False
            }
            self.node.constraints.append(new_constraint)
            self._reload_constraints()

        dlg = RegistryManagerDialog(
            parent=self,
            class_lock=first_class,
            assign_callback=assign_callback
        )
        dlg.exec()

    # ------------------------------------------------------------
    # UTILITY: GET SELECTED CONSTRAINT
    # ------------------------------------------------------------
    def _get_selected_constraint(self):
        # Last clicked row in constraint panel
        # ConstraintRowWidget itself holds the constraint
        for i in range(self.constraint_layout.count()):
            widget = self.constraint_layout.itemAt(i).widget()
            if isinstance(widget, ConstraintRowWidget) and widget.constraint is not None:
                return widget.constraint
        return None

    def _find_root_matrix(self):
        """Return the Matrix agent node if present."""
        ws = getattr(self, "workspace", None)
        if not ws or not hasattr(ws, "controller"):
            return None

        for item in ws.controller.nodes.values():
            if item.node.get_name().lower() == "matrix":
                return item.node
        return None

    def _validate_uid(self):

        if not self.node:
            print("Node not found")
            return

        new_uid = self.uid_edit.text().strip()
        old_uid = self.node.get_universal_id()

        # No change
        if new_uid == old_uid:
            print(f"{new_uid} and {old_uid} are equal")
            return

        # Matrix is immutable
        if self.node.get_name().lower() == "matrix":
            print("matrix is immutable")
            self.uid_edit.setText(old_uid)
            return

        # Check uniqueness across workspace
        ws = self.workspace
        if not ws:
            print("Workspace not found")
            return

        for item in ws.controller.nodes.values():
            other = item.node
            if other is self.node:
                print(f"found {other.name}")
                continue
            if other.get_universal_id() == new_uid:
                # Reject duplicate
                self.uid_edit.setText(old_uid)
                self.uid_edit.setStyleSheet("border:1px solid red;")
                print(f"{new_uid} and {old_uid} are equal")
                return


        # Accept
        self.uid_edit.setStyleSheet("")
        self.node.set_universal_id(new_uid)

        ws.save()

    def clear(self):
        """Reset the inspector UI to a neutral state."""
        # clear whatever widgets you use
        if hasattr(self, "current_node"):
            self.current_node = None
        # if you use forms or labels:
        for w in self.findChildren(QWidget):
            if hasattr(w, "clear"):
                w.clear()
        # optional: show placeholder text
        self.setWindowTitle("Inspector – No agent selected")

    def on_agents_deleted(self, deleted_items):
        """Handle agents removed from the workspace."""
        deleted_gids = {itm.node.get_graph_id() for itm in deleted_items}
        current = getattr(self, "current_node", None)

        # If current node is gone, clear
        if current and current.get_graph_id() in deleted_gids:
            self.clear()
            return

        # If current node’s parent was deleted, show Matrix or nothing
        if current and current.get_parent() in deleted_gids:
            root = self._find_root_matrix()
            if root:
                self.load(root)
            else:
                self.clear()
            return

        # If none of the above, do nothing
        # inspector view remains valid
