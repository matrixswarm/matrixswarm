import os
import json
import hashlib
import uuid
import base64
from copy import deepcopy
from datetime import datetime
from PyQt5 import QtWidgets, QtCore

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QLineEdit
)

from runpy import run_path
from matrix_gui.modules.vault.crypto.deploy_tools import generate_swarm_encrypted_directive, decrypt_swarm_encrypted_directive
from matrix_gui.modules.directive.encryption_staging_dialog import EncryptionStagingDialog
from matrix_gui.modules.directive.ui.deployment_dialog import DeploymentDialog
from matrix_gui.modules.directive.deploy_options_dialog import DeployOptionsDialog
from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.directive.connection_assignment_dialog import ConnectionAssignmentDialog
from matrix_gui.modules.directive.cert_set_dialog import CertSetDialog
from matrix_gui.modules.net.connection_manager_dialog import ConnectionManagerDialog
from matrix_gui.modules.directive.password_prompt_dialog import PasswordPromptDialog
from matrix_gui.modules.directive.deployment.helper.mint_directive_for_deployment import mint_directive_for_deployment
from matrix_gui.modules.directive.deployment.helper.mint_deployment_metadata import mint_deployment_metadata

from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.tagging.security_tags import get_security_tags
from PyQt5.QtWidgets import QInputDialog
from matrix_gui.modules.vault.crypto.cert_utils import set_hash_bang
from PyQt5.QtWidgets import QListWidget, QPushButton, QTextEdit, QLabel
from matrix_gui.modules.vault.crypto.deploy_tools import write_encrypted_bundle_to_file
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from matrix_gui.modules.directive.deployment.wrapper import agent_aggregator_wrapper, agent_connection_wrapper, agent_cert_wrapper, agent_directive_wrapper , agent_signing_cert_wrapper


class DirectiveManagerDialog(QDialog):
    vault_updated = QtCore.pyqtSignal(dict)
    def __init__(self, vault_data, password, vault_path, parent=None):
        super().__init__(parent)

        try:
            self.setWindowTitle("Directive Manager")
            self.setMinimumSize(900, 620)

            self.vault_data = vault_data
            self.password = password
            self.vault_path = vault_path

            self.directives = self.vault_data.setdefault("directives", {})
            self.deployments = self.vault_data.setdefault("deployments", {})

            self.vault_data = vault_data or {}
            if not isinstance(self.vault_data, dict):
                self.vault_data = {}

            v = self.vault_data
            for key, val in (self.vault_data.get("deployments") or {}).items():
                if not isinstance(val, dict):
                    continue  # skip corrupted deployment entries
                label = val.get("label", key)

            for key, val in (self.vault_data.get("directives") or {}).items():
                if not isinstance(val, dict):
                    continue
                label = val.get("label", key)

            main_layout = QVBoxLayout(self)


            lists_row = QHBoxLayout()

            # -- Saved Directives Panel --
            saved_layout = QVBoxLayout()
            saved_layout.addWidget(QLabel("Saved Directives"))
            self.saved_list_widget = QListWidget()
            saved_layout.addWidget(self.saved_list_widget)
            # --- Button row for Saved Directives ---
            saved_btn_row = QHBoxLayout()
            self.load_btn = QPushButton("Load Directive")
            self.save_btn = QPushButton("Save to Vault")
            self.deploy_btn = QPushButton("Deploy")
            self.delete_saved_btn = QPushButton("Delete Saved")
            self.view_certs_btn = QPushButton("View Cert Set")
            saved_btn_row.addWidget(self.load_btn)
            saved_btn_row.addWidget(self.save_btn)
            saved_btn_row.addWidget(self.deploy_btn)
            saved_btn_row.addWidget(self.delete_saved_btn)
            saved_layout.addLayout(saved_btn_row)

            # -- Deployed Directives Panel --
            deployed_layout = QVBoxLayout()
            deployed_layout.addWidget(QLabel("Deployed Directives"))
            self.deployed_list_widget = QListWidget()
            deployed_layout.addWidget(self.deployed_list_widget)
            # --- Button row for Deployed Directives ---
            deployed_btn_row = QHBoxLayout()
            self.delete_deployed_btn = QPushButton("Delete Deployed")
            deployed_btn_row.addWidget(self.delete_deployed_btn)
            deployed_btn_row.addWidget(self.view_certs_btn)
            deployed_layout.addLayout(deployed_btn_row)

            lists_row.addLayout(saved_layout)
            lists_row.addLayout(deployed_layout)
            main_layout.addLayout(lists_row)

            self.editor = QTextEdit()
            self.editor.setPlaceholderText("Edit directive JSON here...")
            main_layout.addWidget(self.editor)
            self.setLayout(main_layout)

            self.view_swarmkey_btn = QPushButton("View Swarm Key")
            self.view_swarmkey_btn.clicked.connect(self.show_swarm_key)

            deployed_btn_row.addWidget(self.view_swarmkey_btn)



            # -- Connect Buttons --
            self.load_btn.clicked.connect(self.load_external_file)
            self.save_btn.clicked.connect(self.save_to_vault)
            self.deploy_btn.clicked.connect(self.deploy_directive)
            self.delete_saved_btn.clicked.connect(self.delete_saved_directive)
            self.delete_deployed_btn.clicked.connect(self.delete_deployed)
            self.view_certs_btn.clicked.connect(self.show_cert_set_dialog)
            self.saved_list_widget.itemClicked.connect(self.load_selected)

            #decrypt a directive to ensure its integrity
            #self.decrypt_directive_btn = QPushButton("Decrypt Directive")
            #self.decrypt_directive_btn.clicked.connect(self.decrypt_and_verify_directive)
            #saved_btn_row.addWidget(self.decrypt_directive_btn)


            #dump vault button and handler
            self.dump_vault_btn = QPushButton("Dump Vault")
            self.dump_vault_btn.clicked.connect(self.dump_vault)
            saved_btn_row.addWidget(self.dump_vault_btn)

            self.vault_key_path = self.vault_path.replace(".json", ".key.enc")
            # (Optional: deployed_list_widget connection if needed for view details, etc.)

            self.refresh_lists()
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)

    def show_swarm_key(self):
        # Ensure a deployment is selected
        item = self.deployed_list_widget.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Select a deployed directive first.")
            return

        dep_id = item.text().split(" :: ")[0].strip()
        dep = (self.vault_data.get("deployments", {}) or {}).get(dep_id)
        if not dep:
            QMessageBox.warning(self, "Not Found", f"Deployment '{dep_id}' not found in vault.")
            return

        swarm_key = dep.get("swarm_key")
        if not swarm_key:
            QMessageBox.warning(self, "No Swarm Key", "This deployment does not have a swarm_key.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Swarm Key")
        layout = QVBoxLayout(dlg)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setLineWrapMode(QTextEdit.NoWrap)  # 🔑 don’t wrap long keys
        text.setPlainText(swarm_key)
        text.setMinimumWidth(600)  # widen the box
        text.setMinimumHeight(120)  # add some vertical space
        layout.addWidget(text)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(swarm_key))
        layout.addWidget(copy_btn)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)

        dlg.resize(800, 200)  # sensible default
        dlg.exec_()


    def dump_vault(self):
        """
        Save the entire self.vault_data to a pretty-printed JSON file for debugging.
        """
        try:
            # Default location: <repo>/matrix_gui/debug/vault-dump-YYYYmmdd-HHMMSS.json
            base_path = resolve_matrixswarm_base()
            debug_dir = base_path / "matrix_gui" / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)

            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            default_path = str(debug_dir / f"vault-dump-{ts}.json")

            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Vault Dump",
                default_path,
                "JSON (*.json);;All Files (*)"
            )
            if not out_path:
                return

            # Write the full vault (no masking, by request)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(self.vault_data, f, indent=2, ensure_ascii=False)

            QMessageBox.information(self, "Vault Dumped",
                                    f"Vault written to:\n{out_path}")

        except Exception as e:
            QMessageBox.critical(self, "Dump Failed", str(e))

    def refresh_list(self):
        self.saved_list_widget.clear()
        for key, val in self.directives.items():
            label = val.get("label", key)
            self.saved_list_widget.addItem(f"{key} :: {label}")

    def show_cert_set_dialog(self):
        item = self.deployed_list_widget.currentItem()
        if not item:
            return
        dep_id = item.text().split(" :: ")[0].strip()
        dep = (self.vault_data.get("deployments", {}) or {}).get(dep_id)
        cert_profile = dep.get("certs") if dep else None
        if not cert_profile:
            QMessageBox.warning(self, "No Certs", "No cert set found for this deployment.")
            return
        dlg = CertSetDialog(cert_profile, self)
        dlg.exec_()

    def delete_deployed(self):
        item = self.deployed_list_widget.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Select a deployed directive to delete.")
            return

        dep_id = item.text().split(" :: ")[0].strip()
        deps = self.vault_data.get("deployments", {})
        if dep_id not in deps:
            QMessageBox.warning(self, "Not Found", f"Deployment '{dep_id}' not found in vault.")
            return

        resp = QMessageBox.question(self, "Delete Deployment",
                                    f"Are you sure you want to delete {dep_id}?",
                                    QMessageBox.Yes | QMessageBox.No)
        if resp != QMessageBox.Yes:
            return

        deps.pop(dep_id, None)
        EventBus.emit("vault.update", vault_path=self.vault_path,
                      password=self.password, data=self.vault_data)
        self.refresh_lists()

    def decrypt_and_verify_directive(self):

        try:
            """Decrypt an encrypted directive JSON file for verification."""
            with open("./matrix_gui/deploy/aaaaa.enc.json", "r") as f:
                encrypted_bundle = json.load(f)

            swarm_key_b64 = "zed_is_dead"
            directive = decrypt_swarm_encrypted_directive(encrypted_bundle, swarm_key_b64)

            # Pretty-print decrypted directive for verification:
            print(json.dumps(directive, indent=2))

        except Exception as e:
            print(f"[decrypt_and_verify_directive][error]: {e}")
            QMessageBox.critical(self, "Error", f"Error decrypt_and_verify_directive alert:\n{e}")

    def refresh_lists(self):
        self.saved_list_widget.clear()
        for key, val in (self.vault_data.get("directives") or {}).items():
            if not isinstance(val, dict):
                continue
            self.saved_list_widget.addItem(f"{key} :: {val.get('label', key)}")

        self.deployed_list_widget.clear()
        for key, val in (self.vault_data.get("deployments") or {}).items():
            if not isinstance(val, dict):
                continue
            self.deployed_list_widget.addItem(f"{key} :: {val.get('label', key)}")

    def delete_saved_directive(self):
        selected_item = self.saved_list_widget.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "No Selection", "Select a saved directive to delete.")
            return

        entry = selected_item.text()
        directive_id = entry.split("::")[0].strip()
        if not directive_id.startswith("directive_"):
            QMessageBox.warning(self, "Invalid Selection", "Directive ID not found.")
            return

        resp = QMessageBox.question(
            self, "Delete Directive",
            f"Are you sure you want to delete {directive_id}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )
        if resp != QMessageBox.Yes:
            return

        if directive_id in self.directives:
            del self.directives[directive_id]
            EventBus.emit(
                "vault.update",
                vault_path=self.vault_path,
                password=self.password,
                data=self.vault_data
            )
            self.refresh_lists()
            QMessageBox.information(self, "Directive Deleted", f"Directive {directive_id} deleted.")

    def load_selected(self):
        item = self.saved_list_widget.currentItem()
        if not item:
            return
        uid = item.text().split(" :: ")[0]
        directive = self.directives.get(uid, {}).get("json", {})
        self.editor.setPlainText(json.dumps(directive, indent=2))

    def load_external_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Directive", "", "JSON or Python (*.json *.py)")
        if not path:
            return
        try:
            if path.endswith(".py"):

                data = run_path(path)["matrix_directive"]

            else:
                with open(path, "r") as f:
                    data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Load Failed", f"Failed to load directive: {e}")
            return

        try:
            self.editor.setPlainText(json.dumps(data, indent=2))
        except Exception as e:
            QMessageBox.warning(self, "Editor Load Error", str(e))

    def save_to_vault(self):

        try:
            directive = json.loads(self.editor.toPlainText())
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))
            return

        hval = hashlib.sha256(json.dumps(directive, sort_keys=True).encode()).hexdigest()

        for uid, meta in self.vault_data.get("directives", {}).items():
            if meta.get("directive_hash") == hval:
                QMessageBox.information(self, "Duplicate Found",
                    f"Already stored as universe ID: {uid}\nLabel: {meta.get('name','unnamed')}")
                return


        label, ok = QInputDialog.getText(self, "Directive Label", "Enter a label for this directive:")
        if not ok or not label.strip():
            return

        uid = "directive_" + uuid.uuid4().hex[:6]
        self.directives[uid] = {
            "label": label.strip(),
            "json": directive
        }

        EventBus.emit(
            "vault.update",
            vault_path=self.vault_path,
            password=self.password,
            data=self.vault_data
        )
        QMessageBox.information(self, "Saved", f"Directive saved to vault as: {uid}")
        self.refresh_list()


    def _open_connection_manager(self):
        dlg = ConnectionManagerDialog(self.vault_data, self)
        dlg.exec_()
        # self.refresh_deployments()
        self.vault_updated.emit(self.vault_data)

    def preview_deployment(self, directive_copy):
        import json
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton

        dlg = QDialog(self)
        dlg.setWindowTitle("Preview Deployment")
        dlg.resize(800, 600)

        layout = QVBoxLayout(dlg)

        view = QTextEdit()
        view.setReadOnly(True)
        view.setText(json.dumps(directive_copy, indent=2))
        layout.addWidget(view)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.close)
        layout.addWidget(btn_close)

        dlg.exec_()

    def deploy_directive(self):

        try:

            # step 1. Select directive from vault
            item = self.saved_list_widget.currentItem()
            if not item:
                QMessageBox.warning(self, "No Selection", "Select a saved directive first.")
                return

            directive_id = item.text().split("::")[0].strip()
            directive = self.directives.get(directive_id)
            if not directive or "json" not in directive:
                QMessageBox.warning(self, "Missing Data", "Selected directive data is missing.")
                return

            # step 2. Generate deployment ID and label
            deployment_id = f"{uuid.uuid4().hex[:16]}"
            label, ok = QInputDialog.getText(
                self, "Deployment Label", "Provide a friendly deployment label:",
                text=directive.get("label", "")
            )
            if not ok or not label.strip():
                return

            # step 3. Deepcopy and prepare the directive template
            template_directive = deepcopy(directive["json"])
            agent_aggregator = agent_aggregator_wrapper(template_directive)

            # step 4. Connection assignment via ConnectionAssignmentDialog
            conn_mgr = self.vault_data.get("connection_manager", {})

            # Handle agents from either "agents" or "children"
            if not agent_aggregator.count():
                QMessageBox.warning(self, "No Agents", "No agents found in the deployment directive.")
                return

            wrapped_agents = agent_connection_wrapper(agent_aggregator)

            conn_dlg = ConnectionAssignmentDialog(self, wrapped_agents, conn_mgr)
            if conn_dlg.exec_() == conn_dlg.Accepted:
                conn_dlg.apply_assignments()
            else:
                QMessageBox.warning(self, "No Assignments", "Connection assignments required.")
                return

            wrapped_agents = agent_cert_wrapper(agent_aggregator)
            #inject certs
            EventBus.emit("crypto.service.connection_cert.injector", wrapped_agents)

            wrapped_agents = agent_signing_cert_wrapper(agent_aggregator)
            #inject signing keys
            EventBus.emit("crypto.service.signing_cert.injector", wrapped_agents)

            wrapped_agents = agent_directive_wrapper(agent_aggregator)

            # step 5. Mint the final runtime directive (from template + deployment)
            directive_staging = mint_directive_for_deployment(template_directive, wrapped_agents, deployment_id)

            # step 6. Options Dialog (Clown Car, Hashbang)
            opts_dialog = DeployOptionsDialog(self)
            if opts_dialog.exec_() != QDialog.Accepted:
                QMessageBox.information(self, "Cancelled", "Deployment process cancelled by operator.")
                return
            opts = opts_dialog.get_options()

            # step 7. Preview the newly minted directive (only once)
            staging_dialog = EncryptionStagingDialog(json.dumps(directive_staging, indent=2), self)
            if staging_dialog.exec_() != QDialog.Accepted:
                QMessageBox.information(self, "Cancelled", "Directive encryption cancelled by operator.")
                return

            clown_car = bool(opts["clown_car"])
            hashbang = bool(opts["hashbang"])

            # step 8.  Encrypt the directive
            bundle, aes_key, directive_hash = generate_swarm_encrypted_directive(directive_staging, clown_car, hashbang)

            # step 9. Choose save location (default under /deploy/)
            base_path = resolve_matrixswarm_base()
            deploy_dir = base_path / "matrix_gui/deploy"
            deploy_dir.mkdir(parents=True, exist_ok=True)

            default_path = str(deploy_dir / f"{label.strip()}.enc.json")

            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Encrypted Directive",
                default_path,
                "Encrypted JSON (*.enc.json);;All Files (*)"
            )

            # If user cancels, fall back to default auto-save
            if not out_path:
                out_path = default_path

            write_encrypted_bundle_to_file(bundle, out_path)

            # step 10. Update deployment record in the vault with encryption details
            with open(out_path, "rb") as f:
                encrypted_hash = hashlib.sha256(f.read()).hexdigest()

            deployment_record = mint_deployment_metadata(
                template_directive=template_directive,
                wrapped_agents=wrapped_agents,
                deployment_id=deployment_id,
                label=label.strip(),
                source_directive_id=directive_id,
                aes_key_b64=base64.b64encode(aes_key).decode(),
                encrypted_path=out_path,
                encrypted_hash=encrypted_hash,
            )

            # Persist in vault (single write; CRUD is trivial now)
            self.vault_data.setdefault("deployments", {})[deployment_id] = deployment_record

            # Emit + refresh UI
            EventBus.emit(
                "vault.update",
                vault_path=self.vault_path,
                password=self.password,
                data=self.vault_data
            )
            self.refresh_lists()

            # step 11. Show final deploy command to operator
            deploy_cmd = f"""
            🚀 Your directive has been encrypted and saved.

            To deploy from command line, use:

            matrixswarm-boot --universe ai --reboot \\
              --encrypted-directive "{out_path}" \\
              --swarm_key {base64.b64encode(aes_key).decode()}
            """
            DeploymentDialog(deploy_cmd, self).exec_()

        except Exception as e:
            print(f"Failed directive creation: {e}")
            QMessageBox.critical(self, "Error", f"Deployment error alert:\n{e}")
















