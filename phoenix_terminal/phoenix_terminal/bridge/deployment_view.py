"""Private deployment adapters; only explicit public projections cross the API."""
from copy import deepcopy
import base64
import hashlib
import json

from .permissions import validate_changes


def agent_nodes(value):
    """Accept both existing flat metadata and the newer compiled agent tree."""
    stack = list(reversed(value)) if isinstance(value, list) else [value]
    result = []
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            raise ValueError("Deployment agent inventory is invalid.")
        result.append(node)
        if len(result) > 4096:
            raise ValueError("Deployment agent inventory exceeds the supported limit.")
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Deployment child inventory is invalid.")
        stack.extend(reversed(children))
    return result


def _sealed_agent(deployment, agent_id):
    from matrix_gui.modules.vault.crypto.deploy_tools import decrypt_swarm_encrypted_directive
    bundle, key = deployment.get("encrypted_bundle"), deployment.get("swarm_key")
    if not isinstance(bundle, dict) or not isinstance(key, str):
        raise ValueError("Saved settings require a sealed deployment. Prepare it in Phoenix first.")
    try:
        root = decrypt_swarm_encrypted_directive(bundle, key)
        matches = [a for a in agent_nodes(root) if a.get("universal_id") == agent_id]
        if len(matches) != 1 or not isinstance(matches[0].get("config"), dict):
            raise ValueError("Missing or ambiguous agent configuration.")
        meta = [a for a in agent_nodes(deployment.get("agents", [])) if a.get("universal_id") == agent_id]
        if len(meta) != 1 or meta[0].get("name") != matches[0].get("name"):
            raise ValueError("Agent identity does not match sealed directive.")
        return root, matches[0]
    except Exception:
        raise ValueError("Phoenix could not verify this agent's sealed configuration. Ask the operator to inspect the deployment.") from None


def configured_agent(deployment, agent_id):
    _, agent = _sealed_agent(deployment, agent_id)
    return agent


def update_sealed_config(deployment, agent_id, changes):
    """Modify only allowed fields, retaining identities, source hashes and keys."""
    from matrix_gui.modules.vault.crypto.deploy_tools import encrypt_data
    root, agent = _sealed_agent(deployment, agent_id)
    changes = validate_changes(agent, changes)
    if all(agent["config"].get(field) == value for field, value in changes.items()):
        return
    agent["config"].update(changes)
    key = base64.b64decode(deployment["swarm_key"], validate=True)
    bundle = encrypt_data(json.dumps(root, indent=2).encode("utf-8"), key)
    deployment["encrypted_bundle"] = bundle
    deployment["encrypted_hash"] = hashlib.sha256(
        json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    # The edited bundle is a different operation, never an original-boot retry.
    deployment.pop("railgun_request_id", None)
    options = deployment.get("railgun_boot_options")
    if isinstance(options, dict):
        options.pop("railgun_request_id", None)
    # Some deployment formats duplicate configuration in their private metadata.
    # Keep only existing copies in agreement; credentials remain untouched.
    for metadata in agent_nodes(deployment.get("agents", [])):
        if metadata.get("universal_id") == agent_id and isinstance(metadata.get("config"), dict):
            for field, value in changes.items():
                if field in metadata["config"]:
                    metadata["config"][field] = deepcopy(value)
