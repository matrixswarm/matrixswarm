"""
Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
Module: Deploy Options Dialog

This module provides the `DeployOptionsDialog` class, a PyQt6-based dialog for configuring directive deployment options.
The dialog allows users to toggle various deployment settings (e.g., embedding agent sources, directive preview) and can
integrate with external callbacks for managing and refreshing connection hosts.

---

Classes:
    - DeployOptionsDialog: A dialog for configuring deployment options.

---

class DeployOptionsDialog(QDialog):
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QDialogButtonBox, QCheckBox, QToolButton, QGroupBox, QLabel, QComboBox, QLineEdit
)
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class DeployOptionsDialog(QDialog):
    def __init__(self, ssh_map:dict, label:str, parent=None):
        super().__init__(parent)

        try:
            self.setWindowTitle("Directive Deployment Options")
            self.setMinimumWidth(420)

            self._manage_conn_cb = None
            self._refresh_hosts_cb = None

            self.clown_car_cb = QCheckBox("Embed agent sources (Clown Car)")
            self.clown_car_cb.setChecked(False)

            #self.hashbang_cb = QCheckBox("Add hashbang")
            #self.hashbang_cb.setChecked(True)

            self.preview_cb = QCheckBox("View the fully resolved directive after dependency to agent mappings")
            self.preview_cb.setChecked(True)

            manage_btn = QToolButton()
            manage_btn.setText("⋯")  # small manage button
            manage_btn.setToolTip("Open Manage Connections")
            manage_btn.clicked.connect(self._manage_and_refresh)

            self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)

            layout = QVBoxLayout(self)
            rg_box = QGroupBox("Preview")
            rg_lay = QVBoxLayout()
            rg_lay.addWidget(self.preview_cb)
            #layout.addWidget(self.hashbang_cb)
            rg_box.setLayout(rg_lay)
            layout.addWidget(rg_box)

            rg_box = QGroupBox("Clown Car")
            rg_lay = QVBoxLayout()
            rg_lay.addWidget(self.clown_car_cb)
            #layout.addWidget(self.hashbang_cb)
            rg_box.setLayout(rg_lay)
            layout.addWidget(rg_box)

            # Initialize Rail-Gun Section
            rg_box = QGroupBox("Railgun Launch && Boot Flags (Optional)")
            rg_lay = QVBoxLayout()

            self.chk_railgun = QCheckBox("Enable Railgun Upload + Remote Boot")
            self.ssh_selector = QComboBox()
            rg_lay.addWidget(self.chk_railgun)
            rg_lay.addWidget(QLabel("SSH Target:"))
            rg_lay.addWidget(self.ssh_selector)

            # Input for Universe Name
            self.universe_name_edit = QLineEdit()
            try:
                label = label.strip()
            except Exception:
                pass

            if(label):
                self.universe_name_edit.setText(label)

            self.universe_name_edit.setPlaceholderText("Universe Name")  # Placeholder text
            rg_lay.addWidget(QLabel("Enter Universe Name:"))
            rg_lay.addWidget(self.universe_name_edit)

            if not isinstance(ssh_map, dict):
                ssh_map={}

            for sid, meta in ssh_map.items():
                label = meta.get("label", sid)
                self.ssh_selector.addItem(f"{label} ({meta.get('host', '?')})", meta)

            # === Boot Flags ===

            self.flag_reboot = QCheckBox("--reboot  (Restart agents without full reinit)")
            self.flag_reboot.setToolTip("Restart agents in the current universe without full reinitialization.")
            rg_lay.addWidget(self.flag_reboot)

            self.flag_verbose = QCheckBox("--verbose  (Enable stdout logging)")
            self.flag_verbose.setToolTip("Enable stdout logging for spawned agents.")
            rg_lay.addWidget(self.flag_verbose)

            self.flag_debug = QCheckBox("--debug  (Enable verbose internal debugging output)")
            self.flag_debug.setToolTip("Enable verbose internal debugging output.")
            rg_lay.addWidget(self.flag_debug)

            self.flag_rugpull = QCheckBox("--rug-pull  (Each agent's run-file self-deletes after boot)")
            self.flag_rugpull.setToolTip("Force rug-pull mode: each agent's pod-run-file self-deletes after boot.")
            rg_lay.addWidget(self.flag_rugpull)

            self.flag_clean = QCheckBox("--clean  (Purge runtime directories before boot)")
            self.flag_clean.setToolTip("Purge all runtime directories before booting.")
            rg_lay.addWidget(self.flag_clean)

            self.flag_reboot_new = QCheckBox("--reboot-new  (Create fresh reboot UUID)")
            self.flag_reboot_new.setToolTip("Force creation of a new reboot UUID (fresh timestamp).")
            rg_lay.addWidget(self.flag_reboot_new)

            self.flag_reboot_id = QLineEdit()
            self.flag_reboot_id.setPlaceholderText("UUID (for --reboot-id)")
            self.flag_reboot_id.setToolTip("Resume a specific previous reboot UUID directory.")
            rg_lay.addWidget(self.flag_reboot_id)

            rg_box.setLayout(rg_lay)
            layout.addWidget(rg_box)

            layout.addWidget(self.buttons)

            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)

        except Exception as e:
            emit_gui_exception_log("DeployOptionsDialog.__init__", e)

    def _manage_and_refresh(self):
        if callable(self._manage_conn_cb):
            self._manage_conn_cb()
        if callable(self._refresh_hosts_cb):
            hosts = list(dict.fromkeys(self._refresh_hosts_cb() or []))  # de-dupe, keep order

    def validate_and_get_universe_name(self) -> str:
        """
        Validates the user input for the universe name. If the input is invalid,
        returns the default "phoenix".

        Returns:
            str: A valid universe name.
        """
        universe_name = self.universe_name_edit.text().strip()

        # Check if the universe name is valid (only alphanumeric)
        if not universe_name or not universe_name.isalnum():
            return "phoenix"

        return universe_name


    def get_options(self):
        return {

            "clown_car": self.clown_car_cb.isChecked(),
            "preview": self.preview_cb.isChecked(),
            "railgun_enabled": self.chk_railgun.isChecked(),
            "railgun_target": self.ssh_selector.currentData(),
            "reboot": self.flag_reboot.isChecked(),
            "verbose": self.flag_verbose.isChecked(),
            "debug": self.flag_debug.isChecked(),
            "rug_pull": self.flag_rugpull.isChecked(),
            "clean": self.flag_clean.isChecked(),
            "reboot_new": self.flag_reboot_new.isChecked(),
            "reboot_id": self.flag_reboot_id.text().strip() or None,
            "universe": self.validate_and_get_universe_name() ,
        }