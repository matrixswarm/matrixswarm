from PyQt6.QtWidgets import (
    QWidget, QGridLayout, QLabel
)
from PyQt6.QtWidgets import QToolButton

from matrix_gui.registry.registry_manager import RegistryManagerDialog
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_resolver import ConstraintResolver


class ConstraintRowWidget(QWidget):
    """
    Commander Edition Constraint Renderer

    RULES:

    • If AUTOGEN constraint:
        - No assign/remove/switch/edit buttons
        - Show 'autogen' tag
        - Path visible
        - Locked

    • If USER-ASSIGNABLE constraint (editor exists):
        - Show assign/reassign button
        - No edit/remove/switch buttons
        - Show 'required' tag

    • If INVALID constraint:
        - Show INVALID tag (red)
        - No buttons
    """

    def __init__(self, constraint, edit_callback, remove_callback, change_callback=None):
        super().__init__()
        super().__init__()
        self.constraint = constraint
        self.edit_callback = edit_callback
        self.remove_callback = remove_callback
        self.change_callback = change_callback

        self._constraint_resolver = ConstraintResolver()
        self.cls = constraint["class"]
        self.flags = self._classify(self.cls, constraint)

        self._build_ui()
        self._render_row()

    def _build_ui(self):
        self.layout = QGridLayout(self)

        self.icon = QLabel()
        self.icon.setStyleSheet("padding:4px;")
        self.layout.addWidget(self.icon)

        self.class_label = QLabel(self.cls)
        self.class_label.setStyleSheet("font-weight:bold; color:#fff; padding:4px 0px;")
        self.layout.addWidget(self.class_label)

        self.path_label = QLabel()
        self.path_label.setStyleSheet("color:#bbb; padding:4px 8px;")
        self.layout.addWidget(self.path_label)

    def _render_row(self):
        # clear layout
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        flags = self.flags
        met = bool(self.constraint.get("met"))

        # --- COL 0: ICON ---
        icon = QLabel("✅" if met else "⚙️")
        icon.setStyleSheet(
            f"font-size:16px; padding:4px; color:{'#66ff66' if met else '#888'};"
        )
        self.layout.addWidget(icon, 0, 0)

        # --- COL 1: NAME ---
        name = QLabel(self.cls)
        name.setStyleSheet("""
            font-weight:600;
            color:#f0f0f0;
            padding:4px 10px;
            font-size:13px;
        """)
        self.layout.addWidget(name, 0, 1)

        # --- COL 2: ASSIGN (or spacer) ---
        if flags["is_assignable"] and not flags["is_auto"]:
            btn = QToolButton()
            btn.setText("🛠")
            btn.setToolTip("Assign or change")
            btn.setStyleSheet("""
                QToolButton {
                    background:#1a1a1a;
                    border:1px solid #555;
                    border-radius:6px;
                    font-size:14px;
                }
                QToolButton:hover {
                    background:#222;
                    border-color:#aaa;
                }
            """)
            btn.setFixedSize(36, 28)
            btn.clicked.connect(self._on_assign)
            self.layout.addWidget(btn, 0, 2)
        else:
            self.layout.addWidget(QWidget(), 0, 2)  # spacer

        # --- COL 3: STATUS CHIP ---
        if flags["is_auto"]:
            text, color, bg = "AUTOGEN", "#33ff66", "rgba(0,255,0,0.08)"
        elif met:
            text, color, bg = "SATISFIED", "#33ccff", "rgba(0,170,255,0.08)"
        else:
            text, color, bg = "REQUIRED", "#ffbb44", "rgba(255,170,0,0.08)"

        chip = QLabel(text)
        chip.setStyleSheet(f"""
            background:{bg};
            border:1px solid {color};
            border-radius:6px;
            color:{color};
            padding:4px 12px;
            font-size:12px;
            font-weight:600;
        """)
        self.layout.addWidget(chip, 0, 3)

    def _add_assign_button(self):
        btn = QToolButton()
        btn.setText("⚙️")
        btn.setToolTip("Assign or change this requirement")
        btn.setStyleSheet("""
            QToolButton {
                background-color: #111;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px;
            }
            QToolButton:hover {
                background-color: #222;
            }
        """)
        btn.clicked.connect(self._on_assign)

        btn.setFixedSize(32, 32)  # perfectly squares it up to match the row height
        self.layout.addWidget(btn)

    def _classify(self, cls_name, constraint):
        return {
            "is_auto": self._constraint_resolver.is_autogen(cls_name),
            "is_assignable": self._constraint_resolver.has_editor(cls_name),
            "has_serial": bool(constraint.get("serial")),
            "path": self._compute_path(constraint)
        }

    # =============================================================
    # Helpers
    # =============================================================

    def _compute_path(self, constraint):
        """Compute the path for the assigned provider (if any)."""
        if not constraint.get("serial"):
            return "(no path)"

        try:
            vcs = VaultCoreSingleton.get()
            store = vcs.get_store("registry")
            namespace = store.get_namespace(constraint["class"])
            obj = namespace.get(constraint["serial"])
            if obj:
                return obj.get("path", "(no path)")
        except Exception:
            pass

        return "(no path)"


    # =============================================================
    # Button Handlers
    # =============================================================

    def _on_assign(self):
        cls = self.constraint["class"]

        def assign_callback(class_name, serial):
            # Write assignment directly back into the constraint
            self.constraint["serial"] = serial
            self.constraint["met"] = True
            # Refresh UI
            if self.change_callback:
                self.change_callback()

        # open Registry Manager with class lock (only relevant namespace)
        dlg = RegistryManagerDialog(
            parent=self,
            class_lock=cls,
            assign_callback=assign_callback
        )
        dlg.exec()

