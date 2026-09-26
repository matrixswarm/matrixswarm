"""Remove only captured, unchanged vault records after a fresh successful boot."""
from copy import deepcopy
import ipaddress


def target(record):
    identity = record.get("railgun_target_identity") or {}
    try:
        return (str(ipaddress.ip_address(identity["host"])), int(identity.get("port", 22)))
    except (ValueError, KeyError, TypeError):
        return None


def prepare_cleanup(vault, deployment_id, enabled):
    records = vault.data.get("deployments", {})
    current = deepcopy(records[deployment_id])
    candidates = {key: deepcopy(record) for key, record in records.items()
                  if enabled and key != deployment_id and isinstance(record, dict)
                  and current.get("universe") and record.get("universe") == current["universe"]
                  and target(current) is not None and target(record) == target(current)}
    used = False

    def finish():
        nonlocal used
        if used:
            return 0
        # Never apply to another unlocked vault or to a changed deployment.
        from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
        if VaultCoreSingleton.get() is not vault:
            raise RuntimeError("Original vault is no longer active")
        removed = []
        def transform(latest):
            if latest.get(deployment_id) != current:
                raise RuntimeError("Current deployment changed during launch")
            removed.extend(key for key, record in candidates.items() if latest.get(key) == record)
            for key in removed:
                del latest[key]
            return latest
        if not vault.transform_section("deployments", transform):
            raise RuntimeError("Vault rejected deployment cleanup")
        used = True
        return len(removed)
    return finish
