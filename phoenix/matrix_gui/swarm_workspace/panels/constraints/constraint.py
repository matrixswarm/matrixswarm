# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QComboBox, QMessageBox, QDialog, QDialogButtonBox,QSizePolicy
)
from PyQt6.QtCore import Qt
from .constraint_row_widget import ConstraintRowWidget
from matrix_gui.registry.registry_manager import RegistryManagerDialog
from matrix_gui.registry.object_classes import EDITOR_REGISTRY
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
class Constraint(QWidget):
    """
    The UI section inside Agent Inspector that shows
    all constraint objects for the agent.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.agent = None    # updated by AgentInspector
        self.class_list = [] # populated from PROVIDERS/EDITORS

        self.layout = QVBoxLayout(self)

        self.header = QLabel("Requirements")
        self.header.setStyleSheet("font-size:14px; font-weight:bold; color:#bbb;")
        self.layout.addWidget(self.header)

        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows_container.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed
        )
        self.rows_container.setMaximumHeight(self.rows_container.sizeHint().height())
        self.layout.addWidget(self.rows_container)
        self.layout.setAlignment(self.rows_container, Qt.ItemDataRole.AlignTop)

        self.constraint_rows = []

        # Add button
        self.add_btn = QPushButton("+ Add Requirement")
        self.add_btn.clicked.connect(self._add_requirement)
        self.layout.addWidget(self.add_btn)

    # -------------------------------------------------------------
    def load(self, agent, class_list):
        self.agent = agent
        self.class_list = class_list

        # --- FIRST: purge any accidental leftover rows in main layout ---
        for i in reversed(range(self.layout.count())):
            w = self.layout.itemAt(i).widget()
            if isinstance(w, ConstraintRowWidget):
                self.layout.removeWidget(w)
                w.setParent(None)

        # --- Clear container rows properly ---
        for r in self.constraint_rows:
            self.rows_layout.removeWidget(r)
            r.setParent(None)
            r.deleteLater()
        self.constraint_rows.clear()
        self.rows_layout.invalidate()
        self.rows_container.updateGeometry()


        if "constraints" not in self.agent:
            self.agent["constraints"] = []

        # --- Insert fresh rows into rows_layout ---
        for constraint in agent["constraints"]:
            row = ConstraintRowWidget(
                constraint,
                edit_callback=self._edit_constraint,
                remove_callback=self._remove_constraint,
                change_callback=lambda: self.load(self.agent, self.class_list)
            )
            self.rows_layout.addWidget(row)
            self.constraint_rows.append(row)

        # Tell the AgentItem to update its border color
        ws = self.parent().workspace
        item = ws.controller.nodes[self.agent["graph_id"]]
        item.update_status_color()
        self.rows_container.adjustSize()
        self.rows_container.setMaximumHeight(self.rows_container.sizeHint().height())

    # -------------------------------------------------------------
    def _add_requirement(self):
        """
        Show dropdown of all available classes.
        After selection, open RegistryManagerDialog(assign_for=<class>)
        """
        dlg = ClassSelectionDialog(self.class_list, self)
        cls = dlg.get_selection()
        if not cls:
            return

        new_obj = {
            "class": cls,
            "raw": {},
            "serial": None,
            "auto": False,
            "met": False
        }

        self.agent["constraints"].append(new_obj)

        # Immediately open manager to pick resource object
        def accept_callback(class_name, serial):
            new_obj["serial"] = serial
            new_obj["met"] = True
            self.load(self.agent, self.class_list)

        mgr = RegistryManagerDialog( parent=self, class_lock=cls, assign_callback=accept_callback)

        mgr.exec()

    # -------------------------------------------------------------
    def _edit_constraint(self, constraint):
        """
        Double-click behavior of requirement:
        • If auto → show message
        • If has serial → open editor
        • If incomplete → open registry manager for assignment
        """
        cls = constraint["class"]

        # Auto-gen classes show a notice only
        if constraint["auto"]:
            QMessageBox.information(self, "Auto Generated",
                                    "This object is automatically generated at deploy time.")
            return

        # If serial is assigned → open the editor for this class-object
        if constraint.get("serial"):
            cls = constraint["class"]

            # Pull live registry store
            vcs = VaultCoreSingleton.get()
            registry_store = vcs.get_store("registry")
            ns = registry_store.get_namespace(cls)

            obj = ns.get(constraint["serial"])
            if not obj:
                QMessageBox.warning(self, "Missing", "This registry object no longer exists.")
                return

            editor_cls = EDITOR_REGISTRY[cls]
            editor = editor_cls(new_conn=False)
            editor._load_data(obj)

            if editor.exec():
                updated = editor.serialize()
                updated["class"] = cls
                updated["path"] = editor.get_directory_path()
                updated["serial"] = constraint["serial"]

                ns[constraint["serial"]] = updated
                registry_store.commit()
                constraint["met"] = True
                self.load(self.agent, self.class_list)
            return

        # If no serial → open assign mode
        def accept_callback(class_name, serial):
            constraint["serial"] = serial
            constraint["met"] = True
            self.load(self.agent, self.class_list)

        mgr = RegistryManagerDialog(parent=self, class_lock=cls, assign_callback=accept_callback)

        mgr.exec()

    # -------------------------------------------------------------
    def _remove_constraint(self, constraint):
        """
        Removable only if NOT auto.
        """
        if constraint["auto"]:

            QMessageBox.warning(self, "Protected", "This requirement cannot be removed.")
            return

        self.agent["constraints"].remove(constraint)
        self.load(self.agent, self.class_list)

# -------------------------------------------------------------
# Class selection popup for +Add
# -------------------------------------------------------------
class ClassSelectionDialog(QDialog):
    def __init__(self, class_list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Requirement Class")

        layout = QVBoxLayout(self)
        self.combo = QComboBox()
        self.combo.addItems(class_list)
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def get_selection(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.combo.currentText()
        return None
