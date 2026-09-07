# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import json
import hashlib
import uuid
import base64
from datetime import datetime
from copy import deepcopy
from PyQt6.QtWidgets import QMessageBox, QDialog, QInputDialog

from matrix_gui.modules.vault.crypto.deploy_tools import generate_swarm_encrypted_directive
from matrix_gui.modules.directive.encryption_staging_dialog import EncryptionStagingDialog
from matrix_gui.modules.directive.deploy_options_dialog import DeployOptionsDialog
from .agent_root_validator import AgentRootValidator
from .dialog.railgun import RailgunDialog
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.modules.railgun.remote_shell import derive_runtime_capabilities

class Deploy():

    def deploy_directive(self, parent_dialog, directive_staging, deployment_staging, workspace_id):
        try:

            vcs = VaultCoreSingleton.get()

            # step 2. Generate deployment ID and label
            deployment_id = f"{uuid.uuid4().hex[:16]}"

            label, ok = QInputDialog.getText(None, "Deployment Label", "Provide a friendly deployment label:")
            if not ok or not label.strip():
                return


            # FOR RAILGUN SUPPORT
            ssh_map = None
            reg = vcs.get_store("registry")

            # Get all SSH registry objects
            ssh_namespace = reg.get_namespace("ssh") or {}

            ssh_map = deepcopy(ssh_namespace)

            # Options Dialog (Clown Car, Hashbang)
            opts_dialog = DeployOptionsDialog(ssh_map, label, parent=parent_dialog)
            if opts_dialog.exec() != QDialog.DialogCode.Accepted:
                QMessageBox.information(None, "Cancelled", "Deployment process cancelled by operator.")
                return
            opts = opts_dialog.get_options()
            opts["runtime_capabilities"] = derive_runtime_capabilities(
                directive_staging.get("agents", {})
            )

            # --- Agent source embedding (Clown Car) ---
            """
            Handles the "Clown Car" step in the deployment process by verifying and managing the agent source directory
            used in the directive staging process. Supports caching and verifying agent paths, loading or validating from 
            the vault, and ensuring necessary files are available for deployment.
    
            Steps:
            1. **Check 'Clown Car' Option:**
               - Determines if the "Clown Car" mode is enabled based on the `opts["clown_car"]` flag.
               - Affects how the directive is processed and staged.
    
            2. **Verify Agent Path:**
               - If the "Clown Car" mode is enabled, attempts to load the last cached agent path from the vault.
               - Verifies if the cached path exists and contains all required sources for the directive.
    
            3. **Cache Validation:**
               - If the cached path is invalid or missing necessary files, opens a verification dialog (`AgentRootCheckDialog`) 
                 for the user to select and verify the correct agent source directory.
               - Caches the newly verified path in `self.vault_data` for future deployments.
    
            4. **Generate Encrypted Directive:**
               - Calls `generate_swarm_encrypted_directive` to bundle the directive data along with encryption, 
                 integrating the verified agent path if applicable.
        
            Functions/Methods:
                AgentRootSelector.resolve_agents_root(agent_path): Resolves the root directory of the agent sources.
                AgentRootSelector.verify_all_sources(directive_staging, agents_root): Verifies all required agent sources 
                    exist for the directive staging at the specified root.
                generate_swarm_encrypted_directive(directive_staging, clown_car, hashbang, base_path): Generates an encrypted 
                    directive based on the provided staging data and configuration.
    
            Classes/Dialogs:
                AgentRootCheckDialog: Handles user interaction for verifying and selecting the agent root directory, 
                if no valid cached path exists.
    
            """
            clown_car = bool(opts.get("clown_car", False))
            hashbang = clown_car

            if clown_car:
                cached_paths = []

                last_agent_path = vcs.data.get("last_agent_path")
                if last_agent_path:
                    cached_paths.append(last_agent_path)

                for p in vcs.data.get("agent_roots", []):
                    if p not in cached_paths:
                        cached_paths.append(p)

                validator = AgentRootValidator(directive_staging, cached_paths)
                verified_path = validator.run()

                if not verified_path:
                    # User tapped out — abort deployment
                    print("[CLOWN-CAR][ABORT] User cancelled agent validation.")
                    return

                agent_path = verified_path
            else:
                agent_path = None


            try:

                bundle, aes_key, directive_hash = generate_swarm_encrypted_directive(directive_staging['agents'], clown_car=clown_car, hashbang=hashbang, base_path=agent_path)

            except Exception as e:

                print(f"[CLOWN-CAR][ABORT] Missing agent sources detected. Deployment halted. {e}")
                QMessageBox.critical(None, f"Deployment Aborted {e}",
                                     "One or more agent sources could not be located.\n"
                                     "Check console output for details.")
                return

            swarm_key_mem = base64.b64encode(aes_key).decode()

            # Preview the newly minted directive (only once)
            staging_dialog = EncryptionStagingDialog(json.dumps(directive_staging['agents'], indent=2))
            if staging_dialog.exec() != QDialog.DialogCode.Accepted:
                QMessageBox.information(None, "Cancelled", "Directive encryption cancelled by operator.")
                return

            universe = str(opts["universe"]).strip()
            print(
                "[DEPLOY] Railgun sealed-stream mode — directive and swarm "
                "key retained only inside the encrypted Phoenix vault."
            )

            # step 10. Update deployment record in the vault with encryption details
            bundle_bytes = json.dumps(
                bundle, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            encrypted_hash = hashlib.sha256(bundle_bytes).hexdigest()

            deployment_record = {
                "label": label,
                "workspace_id": workspace_id,
                "deployed_at": datetime.now().isoformat(),
                "swarm_key": swarm_key_mem,
                "universe": universe,
                "encrypted_bundle": bundle,
                "encrypted_hash": encrypted_hash,
                "linux_user": opts["linux_user"],
                "runtime_capabilities": opts["runtime_capabilities"],
                "agents": deployment_staging.deployment["agents"],
                "certs": deployment_staging.deployment["certs"],
            }

            # Store chosen SSH target (its serialized registry ID)
            # this will be used later to start, stop, and kill a hive
            ssh_target = opts.get("railgun_target")
            if ssh_target:
                deployment_record["ssh_serial"] = ssh_target.get("serial")

            # Persist in vault (single write; CRUD is trivial now)
            vcs = VaultCoreSingleton.get()
            deployments = vcs.data.setdefault("deployments", {})
            deployments[deployment_id] = deployment_record
            vcs.patch("deployments", deployments)
            #self.refresh_lists()

            ssh_cfg = opts["railgun_target"]
            RailgunDialog.launch(
                parent_dialog, ssh_cfg, bundle, swarm_key_mem, opts
            )

        except Exception as e:
            print(f"Failed directive creation: {e}")
            QMessageBox.critical(None, "Error", f"Deployment error alert:\n{e}")
