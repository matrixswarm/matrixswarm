from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QLabel, QComboBox, QMessageBox, QDialog, QVBoxLayout, QPushButton
)
from PyQt6.QtCore import Qt


class Sentinel(BaseEditor):
    def __init__(self, node, parent=None):
        super().__init__(node, parent)

        # Rewire save button
        self.save_btn.clicked.disconnect()
        self.save_btn.clicked.connect(self._save)

        # A place to store selection if "Watch Specific Agent…" is used
        self.manual_target = None

    # ---------------------------------------------------------
    # BUILD CLEAN UI
    # ---------------------------------------------------------
    def _build_form(self):
        cfg = self.config

        self.mode = QComboBox()
        self.mode.addItems([
            "Passive Sentinel (watch nothing)",
            "Root Guardian (watch Matrix)",
        ])

        self.mode.setToolTip(
            "Select what this sentinel should watch.\n\n"
            "Passive = watches nothing.\n"
            "Root Guardian = resurrects Matrix.\n"
        )

        # REHYDRATE FROM CONFIG
        watched = cfg.get("universal_id_under_watch")

        if watched == "matrix":
            self.mode.setCurrentIndex(1)
        else:
            self.mode.setCurrentIndex(0)

        self.role_status = QLabel()
        self.role_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.layout.addRow("Sentinel Mode:", self.mode)
        self.layout.addRow("Role Status:", self.role_status)

        self.inputs = {}

        self.mode.currentIndexChanged.connect(self._update_role_status)

        # FORCE INITIAL STATUS UPDATE
        self._update_role_status()

    # ---------------------------------------------------------
    # UPDATE EXPLANATION LABEL
    # ---------------------------------------------------------
    def _update_role_status(self):
        option = self.mode.currentIndex()

        if option == 0:
            # Passive
            self.role_status.setText(
                "<b style='color:#6cf'>PASSIVE SENTINEL</b><br>"
                "<i>This sentinel watches nothing and performs no resurrection(unless has children, acting as lightweight guardian.)</i>"
            )
        elif option == 1:
            # Matrix
            self.role_status.setText(
                "<b style='color:#6f6'>ROOT GUARDIAN</b><br>"
                "<i>This sentinel will resurrect <b>Matrix</b> if she goes down.<br>"
                "Only ONE sentinel should hold this responsibility.</i>"
            )


    # ---------------------------------------------------------
    # POPUP LISTING ALL AGENTS FOR SELECTION
    # ---------------------------------------------------------
    def _select_specific_agent(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Select Agent to Watch")

        layout = QVBoxLayout(dlg)

        box = QComboBox()
        box.addItem("(Choose an agent)")
        for child in self.node.get_root().traverse():
            uid = child.get("universal_id")
            if uid:
                box.addItem(uid)

        layout.addWidget(box)

        btn = QPushButton("Confirm")
        layout.addWidget(btn)
        btn.clicked.connect(dlg.accept)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected = box.currentText().strip()
            if selected and selected != "(Choose an agent)":
                self.manual_target = selected
                return True
        return False

    # ---------------------------------------------------------
    # SAVE CONFIG CHANGES
    # ---------------------------------------------------------
    def _save(self):

        mode = self.mode.currentIndex()

        # Passive
        if mode == 0:
            self.node.config.pop("universal_id_under_watch", None)
            self.node.mark_dirty()
            self.accept()
            return

        # Root Guardian – watch Matrix
        if mode == 1:
            # Warn user
            msg = QMessageBox(self)
            msg.setWindowTitle("Assign Root Guardian")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.setText(
                "<b>You are assigning this Sentinel as the ROOT GUARDIAN.</b><br><br>"
                "Matrix cannot resurrect herself because her directive is encrypted.<br>"
                "Only one sentinel in the chain should watch Matrix.<br>"
                "Continue?"
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if msg.exec() != QMessageBox.StandardButton.Ok:
                return

            self.node.config["universal_id_under_watch"] = "matrix"
            self.node.mark_dirty()
            self.accept()
            return






