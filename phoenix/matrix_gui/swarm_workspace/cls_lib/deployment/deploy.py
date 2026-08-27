# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import os
import json
import hashlib
import uuid
import base64
from datetime import datetime
from copy import deepcopy
from PyQt6.QtWidgets import QMessageBox, QDialog, QInputDialog
from pathlib import Path

from matrix_gui.modules.vault.crypto.deploy_tools import generate_swarm_encrypted_directive
from matrix_gui.modules.directive.encryption_staging_dialog import EncryptionStagingDialog
from matrix_gui.modules.directive.ui.deployment_dialog import DeploymentDialog
from matrix_gui.modules.directive.deploy_options_dialog import DeployOptionsDialog
from matrix_gui.core.event_bus import EventBus
from .agent_root_validator import AgentRootValidator
from .dialog.railgun import RailgunDialog
from matrix_gui.modules.vault.crypto.deploy_tools import write_encrypted_bundle_to_file
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton


def _contains_agent(node, agent_name):
    """Return whether a compiled/staged directive contains an agent name."""
    if isinstance(node, dict):
        if node.get("name") == agent_name:
            return True
        return any(_contains_agent(value, agent_name) for value in node.values())
    if isinstance(node, list):
        return any(_contains_agent(value, agent_name) for value in node)
    return False

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
            opts["mcp_worker_enabled"] = _contains_agent(
                directive_staging.get("agents", {}), "mcp_reflex"
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

            # Choose save location (default under /deploy/)
            cwd = Path.cwd()  # This is your working directory (repo root if you launch Phoenix there)
            deploy_dir = cwd / "boot_directives"
            deploy_dir.mkdir(parents=True, exist_ok=True)

            keys_dir = deploy_dir / "keys"
            keys_dir.mkdir(parents=True, exist_ok=True)

            universe = f"{label.strip()}"

            universe_temp = opts.get("universe", False)
            railgun_enabled = bool(opts.get("railgun_enabled", False))
            if universe_temp and railgun_enabled:
                universe = universe_temp.strip()

            out_path = deploy_dir / f"{universe}.enc.json"
            key_path = keys_dir / f"{universe}.key"

            # Directive path
            write_encrypted_bundle_to_file(bundle, out_path)

            # Swarm key path
            if not bool(opts.get("railgun_enabled", False)):
                # Only save to disk if Railgun is NOT used
                print(f"[DEPLOY] Writing swarm key to {key_path}")
                with open(key_path, "w", encoding="utf-8") as f:
                    f.write(base64.b64encode(aes_key).decode())
                os.chmod(key_path, 0o600)
            else:
                print("[DEPLOY] Railgun active — swarm key held in memory only.")

            # step 10. Update deployment record in the vault with encryption details
            with open(out_path, "rb") as f:
                encrypted_hash = hashlib.sha256(f.read()).hexdigest()

            deployment_record = {
                "label": label,
                "workspace_id": workspace_id,
                "deployed_at": datetime.now().isoformat(),
                "swarm_key": swarm_key_mem,
                "encrypted_path": str(out_path),
                "encrypted_hash": encrypted_hash,
                "linux_user": opts["linux_user"],
                "mcp_worker_enabled": opts["mcp_worker_enabled"],
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

            # === Optional Rail-Gun Fire ===
            if bool(opts.get("railgun_enabled", False)):
                ssh_cfg = opts.get("railgun_target", None)
                if ssh_cfg:
                    # pass the key directly
                    RailgunDialog.launch(parent_dialog, ssh_cfg, out_path, swarm_key_mem, opts)
            else:
                # step 11. Show final deploy command to operator
                deploy_cmd = f"""
                🚀 Your directive has been encrypted and saved.
    
                Directive: {out_path}
                Swarm Key: /matrix/boot_directives/keys/{universe}.key
    
                ⚠️ Secure your swarm key:
                    chmod 600 /matrix/boot_directives/keys/{universe}.key
    
                To deploy from command line, use:
    
                    matrixd boot --universe {universe}
    
                Matrix will automatically resolve the encrypted directive and swarm key.
                """
                DeploymentDialog(deploy_cmd).exec()

        except Exception as e:
            print(f"Failed directive creation: {e}")
            QMessageBox.critical(None, "Error", f"Deployment error alert:\n{e}")
