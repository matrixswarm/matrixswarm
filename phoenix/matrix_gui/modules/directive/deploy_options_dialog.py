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
    QDialog, QVBoxLayout, QDialogButtonBox, QCheckBox, QToolButton, QGroupBox, QLabel, QComboBox, QLineEdit, QMessageBox
)
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.railgun.remote_shell import (
    default_linux_user,
    validate_linux_user,
    validate_remote_token,
)

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
            rg_box = QGroupBox("Railgun Launch && Boot Flags (Required)")
            rg_lay = QVBoxLayout()

            self.ssh_selector = QComboBox()
            railgun_notice = QLabel(
                "Railgun streams the sealed directive directly to MatrixD; "
                "no directive or key file is written."
            )
            railgun_notice.setWordWrap(True)
            rg_lay.addWidget(railgun_notice)
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

            # MatrixD starts as this dedicated service account. Railgun creates
            # it when absent and owns the root-only permission setup.
            self.linux_user_edit = QLineEdit()
            try:
                suggested_user = default_linux_user(
                    self.universe_name_edit.text().strip() or "phoenix"
                )
            except ValueError:
                suggested_user = "matrix-phoenix"
            self._suggested_linux_user = suggested_user
            self.linux_user_edit.setText(suggested_user)
            self.linux_user_edit.setPlaceholderText("matrix-phoenix")
            self.linux_user_edit.setToolTip(
                "Least-privilege Linux account used to run Matrix and all native "
                "agents in this universe. Railgun creates it when necessary."
            )
            self.universe_name_edit.textChanged.connect(
                self._update_suggested_linux_user
            )
            rg_lay.addWidget(QLabel("Swarm Linux User:"))
            rg_lay.addWidget(self.linux_user_edit)

            if not isinstance(ssh_map, dict):
                ssh_map={}

            for sid, meta in ssh_map.items():
                label = meta.get("label", sid)
                self.ssh_selector.addItem(f"{label} ({meta.get('host', '?')})", meta)

            # === Boot Flags ===

            self.flag_reboot = QCheckBox("--reboot  (Restart agents without full reinit)")
            self.flag_reboot.setChecked(True)
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

            self.flag_protect_memory = QCheckBox(
                "--protect-memory  (Restrict agent memory and environment to root)"
            )
            self.flag_protect_memory.setChecked(True)
            self.flag_protect_memory.setToolTip(
                "Launch every agent as a Linux non-dumpable process. Other "
                "users, including the swarm account's peer processes, cannot "
                "inspect its memory or environment; root retains access."
            )
            rg_lay.addWidget(self.flag_protect_memory)

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

            self.buttons.accepted.connect(self._accept_if_valid)
            self.buttons.rejected.connect(self.reject)

        except Exception as e:
            emit_gui_exception_log("DeployOptionsDialog.__init__", e)

    def _manage_and_refresh(self):
        if callable(self._manage_conn_cb):
            self._manage_conn_cb()
        if callable(self._refresh_hosts_cb):
            hosts = list(dict.fromkeys(self._refresh_hosts_cb() or []))  # de-dupe, keep order

    def _accept_if_valid(self):
        if self.ssh_selector.currentData() is None:
            QMessageBox.warning(
                self,
                "Railgun Target Required",
                "Create or select a vault-backed SSH target before deployment.",
            )
            return
        try:
            validate_remote_token(
                self.universe_name_edit.text().strip(), "Universe name"
            )
            validate_linux_user(self.linux_user_edit.text(), "Swarm Linux user")
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Railgun Options", str(error))
            return
        self.accept()

    def validate_and_get_universe_name(self) -> str:
        """
        Validates the user input for the universe name. If the input is invalid,
        returns the default "phoenix".

        Returns:
            str: A valid universe name.
        """
        universe_name = self.universe_name_edit.text().strip()

        return validate_remote_token(universe_name, "Universe name")

    def _update_suggested_linux_user(self, universe_name):
        """Track universe edits until the operator overrides the suggestion."""
        if self.linux_user_edit.text().strip() != self._suggested_linux_user:
            return
        try:
            suggestion = default_linux_user(universe_name or "phoenix")
        except ValueError:
            return
        self._suggested_linux_user = suggestion
        self.linux_user_edit.setText(suggestion)


    def get_options(self):
        return {

            "clown_car": self.clown_car_cb.isChecked(),
            "preview": self.preview_cb.isChecked(),
            "railgun_target": self.ssh_selector.currentData(),
            "reboot": self.flag_reboot.isChecked(),
            "verbose": self.flag_verbose.isChecked(),
            "debug": self.flag_debug.isChecked(),
            "rug_pull": self.flag_rugpull.isChecked(),
            "protect_memory": self.flag_protect_memory.isChecked(),
            "clean": self.flag_clean.isChecked(),
            "reboot_new": self.flag_reboot_new.isChecked(),
            "reboot_id": self.flag_reboot_id.text().strip() or None,
            "universe": self.validate_and_get_universe_name() ,
            "linux_user": validate_linux_user(
                self.linux_user_edit.text(), "Swarm Linux user"
            ),
        }
