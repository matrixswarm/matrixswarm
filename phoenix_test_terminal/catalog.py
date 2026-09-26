"""Explicit diagnostic contracts. Associated tests do not imply complete coverage."""

SECTIONS = {
    "cold-start": {
        "purpose": "Full source cockpit with a clean disposable profile, creation and fresh-process unlock.",
        "tests": [],
        "checks": "Import complete cockpit and boot registrations; invoke real modal create/unlock controls; verify locked/unlocked screen and encrypted vault across interpreters.",
        "diagnose": "Do not replace failed imports or cockpit construction with mocks. Missing dependencies, logged errors and incomplete UI initialization fail the adapter.",
        "limits": "Source application, not a packaged binary. Offscreen Qt; file pickers and notifications simulated; no live bridge, deployment or hardware.",
    },
    "editor-validation": {
        "purpose": "Editor validation, safe failure handling and Qt vault-write boundaries.",
        "tests": [],
        "checks": "Real Oracle/Sora/Harvester controls; malformed numbers, dropdowns, text, booleans and roles; Cancel, atomic rejection and corrected retry. Fault-injected editor exceptions, Qt completion affinity, queue failure and closed-vault behavior.",
        "diagnose": "Check fixed-choice combo boxes for silent fallback to their first option; invalid saves must leave the dialog open and config untouched.",
        "limits": "Synthetic local configs; no provider API/model availability checks. Qt button and handler invocation, not native mouse events; only named editors covered.",
    },
    "graph-save": {
        "purpose": "Graph editor save/close failures, mutation autosaves and configuration-editor persistence.",
        "tests": [],
        "checks": "Actual background graph save and closeEvent, submission/worker/atomic-replace failures, Retry button, live vault and ciphertext preservation. Hold a writer to verify GUI heartbeat, newer revisions and pending close; then reload the saved result.",
        "diagnose": "A failed save must not mutate committed workspace data or discard editor changes. A close event must stay rejected until edits are saved or explicitly discarded. Check patch return values and exception handling.",
        "limits": "Offscreen graph; invokes closeEvent directly with a real QCloseEvent. Synthetic storage failures, real encryption and writes in a disposable vault. Legacy non-graph patch calls are still synchronous. No native window-manager, deployment or visual-layout coverage.",
    },
    "workspace-lifecycle": {
        "purpose": "Fresh workspace creation, SSH assignment, graph save/restart and rejected mutations.",
        "tests": [],
        "checks": "Real manager New/Rename/Cancel controls, actual graph editor and loader, row assignment through class-locked registry, serializer and encrypted disk. Reject new/clone/rename/delete saves; exercise WorkspaceStore reads.",
        "diagnose": "Compare graph, manager state and independently reopened vault. Watch live dictionaries mutated before patch accepts, ignored False returns, stale registry serials and incomplete constructors that swallow exceptions.",
        "limits": "Synthetic SSH requirement is seeded on Matrix; assignment uses real controls. Does not test inspector Add Requirement selection, remote deployment or visual layout. Rejected-save slots run directly to capture otherwise fatal Qt callback exceptions.",
    },
    "registry-lifecycle": {
        "purpose": "Real SSH registry create/edit/cancel/validate/save/restart/reload workflow.",
        "tests": [],
        "checks": "Fresh encrypted vault; actual manager buttons and modal editor OK/Cancel signals; process-restart persistence, downstream profile loading, invalid input and rejected commits.",
        "diagnose": "Compare live RegistryStore state with independently decrypted disk. Rejected input/commits must not leave in-memory mutations that a later save can persist. Track serial identity and original creation metadata across edits.",
        "limits": "Synthetic password profile and host only; no network, key installation or workspace assignment. Commit rejection is injected; normal saves use real event wiring and crypto.",
    },
    "vault": {
        "purpose": "Fresh-user vault creation, cancellation, unlock, persistence and credential rotation.",
        "tests": [],
        "checks": "Click real selector/create/unlock/change dialogs offscreen; test missing/corrupt files, wrong credentials/retry, cancellation, session options and simulated YubiKey through the real Qt worker. Execute the production cockpit unlock-routing method with real modal dialogs, crypto, runtime stores and save events. Reopen in a NEW interpreter and retain synthetic registry data.",
        "diagnose": "Missing dependencies are failures. Creation failure: inspect VaultCreateDialog and vault_handler. Runtime/save failure: inspect EventBus, vault_service_loader and VaultCoreSingleton. Reopen failure: check actual on-disk ciphertext, not cached singleton state.",
        "limits": "Not a complete cockpit launch. Routing uses the exact AST-extracted production method without executable startup side effects. Physical YubiKey, legacy migrations, OS dialogs and visual layout remain unverified. Hardware responses, file pickers, notifications and explicitly injected failure cases are simulated; normal crypto and persistence are real.",
    },
    "ssh": {
        "purpose": "Registry SSH onboarding, key management and host trust.",
        "tests": ["test_ssh_key_install_dialog.py", "test_ssh_key_passphrase.py", "test_matrix_ssh_transport.py", "test_matrix_ssh_assignment.py"],
        "checks": "Existing regression assertions for bootstrap versus new-key authentication, host pinning, export, passphrase and duplicate-key behavior.",
        "diagnose": "Trace selected login profile separately from key-to-install. A matching server fingerprint does not prove the new client key is installed. Inspect mocked transport calls and verification identity.",
        "limits": "No production SSH or agent access. Tests use doubles; does not certify a real server or every registry dialog.",
    },
    "deployment": {
        "purpose": "Clown Car source selection, sealed directives and deployment launch contracts.",
        "tests": ["test_clown_car.py", "test_remote_ssh_launch.py", "test_deployment_compiler_isolation.py", "test_deployment_fail_closed.py", "test_deployment_cancellation.py"],
        "checks": "Missing-source retry/cancel, source resolution, exact-byte embedding/hash and remote launch regression tests.",
        "diagnose": "Check wrapper/tree traversal, cached roots, ambiguous agent locations and source/hash consistency. Cancellation must not deploy a partial directive.",
        "limits": "No remote deployment. Successful mock launch is not a golden-swarm boot test.",
    },
    "railgun": {
        "purpose": "Installer responsiveness, progress and failure handling.",
        "tests": ["test_railgun_install_progress.py", "test_railgun_check_lifecycle.py", "test_railgun_upload_cancel.py", "test_railgun_request_receipts.py", "test_matrixd_control_lifecycle.py", "test_deployment_cleanup.py"],
        "checks": "Worker lifecycle, source manifest, upload progress, cancellation and timeouts; durable receipt replay, concurrent/interrupted requests, persisted identities and original-target retry.",
        "diagnose": "Distinguish scanning, SSH negotiation, staging, upload and command execution. A live worker must not block the GUI thread. Lost acknowledgement is unknown, not permission to repeat boot. Check server helper availability and receipt state; never blindly remove active locks. Historical completion is not live health.",
        "limits": "Mock SFTP/SSH and command execution, real temporary receipt files and Qt controls; no live install, Linux crash/power-loss validation or platform packaging certification.",
    },
    "registry": {
        "purpose": "Registry constraints, assignments and persistent state.",
        "tests": ["test_registry_manager_consolidation.py", "test_registry_store_rollback.py", "test_dynamic_universal_ids.py", "test_persistent_state_constraint.py", "test_rsync_boy_profiles.py"],
        "checks": "Existing registry schema, identity, assignment and profile regression assertions.",
        "diagnose": "Compare generic credential fields with agent-owned options. Inspect stale serial references, assignment compatibility and commit validation.",
        "limits": "Some tests inspect source rather than click widgets. No claim of complete dialog behavior coverage.",
    },
    "panels": {
        "purpose": "Custom panels and connection-scoped controls.",
        "tests": ["test_matrix_ssh_panel.py", "test_crypto_panel.py", "test_specialty_panel_activation.py", "test_rsync_boy_live_control.py", "test_rsync_boy_clipboard.py"],
        "checks": "Panel protocol/session filtering, control activation and regression assertions.",
        "diagnose": "Check active session and target IDs, packet contract, delayed replies, stale data and disabled controls. A rendered panel is not proof its remote action works.",
        "limits": "No live agents; unlisted custom panels remain coverage gaps.",
    },
    "startup": {
        "purpose": "Startup policy, first-swarm guidance and workspace behavior.",
        "tests": ["test_phoenix_startup_policy.py", "test_dashboard_onboarding.py", "test_workspace_manager_refresh.py", "test_swarms_control.py"],
        "checks": "Existing startup, dashboard, workspace and swarm regression assertions.",
        "diagnose": "Always compare fresh profile with existing profile. Source-text assertions are supporting evidence, not an end-to-end first-run test.",
        "limits": "Full packaged-app onboarding is not yet automated; source assertions alone cannot clear the release gate.",
    },
    "alerts": {
        "purpose": "Harvester state transitions, delivery and alert decryption.",
        "tests": ["test_harvester_policy.py", "test_harvester_alert_delivery.py", "test_telegram_alert_decrypt.py", "test_email_alert_decrypt.py", "test_discord_alert_decrypt.py"],
        "checks": "Thresholds, startup confirmation, pending delivery and plaintext/decryption regression assertions.",
        "diagnose": "Separate failed observations from confirmed outages; distinguish endpoint discovery, dispatch and recipient acknowledgement. Inspect actual message content.",
        "limits": "No Telegram/email/Discord requests. Isolated SSH subprocess checks and a disposable remote swarm need dedicated integration adapters.",
    },
}

# Only claims that these classes have a behavioral adapter, NOT full path coverage.
BEHAVIORAL_ADAPTERS = {
    f"phoenix/matrix_gui/modules/vault/{module}.py:{name}": "vault"
    for module, name in (
        ("vault_selector_dialog", "VaultSelectorDialog"),
        ("vault_create_dialog", "VaultCreateDialog"),
        ("vault_unlock_dialog", "VaultUnlockDialog"),
        ("vault_change_password_dialog", "VaultChangePasswordDialog"),
    )
}
BEHAVIORAL_ADAPTERS.update({
    "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/oracle.py:Oracle": "editor-validation",
    "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/sora.py:Sora": "editor-validation",
    "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/harvester.py:Harvester": "editor-validation",
    "phoenix/matrix_gui/modules/vault/services/workspace_writer.py:WorkspaceWriter": "graph-save",
    "phoenix/matrix_gui/registry/registry_manager.py:RegistryManagerDialog": "registry-lifecycle",
    "phoenix/matrix_gui/registry/object_classes/editors/ssh.py:SSH": "registry-lifecycle",
    "phoenix/matrix_gui/swarm_workspace/workspace_manager.py:WorkspaceManagerDialog": "workspace-lifecycle",
    "phoenix/matrix_gui/swarm_workspace/swarm_workspace.py:SwarmWorkspaceDialog": "workspace-lifecycle",
    "phoenix/matrix_gui/swarm_workspace/panels/constraints/constraint_row_widget.py:ConstraintRowWidget": "workspace-lifecycle",
})

RELEASE_GAPS = [
    "Packaged Phoenix cold start through cockpit entry and clean shutdown",
    "Disposable MatrixOS golden swarm: connect, deploy, observe, fail, recover, stop",
    "Legacy vault migration and real hardware/platform validation",
    "Behavioral adapters for all inventoried dialogs/widgets/workers and their error/cancel paths",
]
