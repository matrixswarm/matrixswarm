from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from typing import List, Dict
from datetime import datetime

def _walk_nodes(root: dict):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        for c in reversed(node.get("children", []) or []):
            stack.append(c)

def mint_deployment_metadata(
    template_directive: dict,
    wrapped_agents: List,  # AgentDirectiveWrapper
    *,
    deployment_id: str,
    label: str,
    source_directive_id: str,
    aes_key_b64: str,
    encrypted_path: str,
    encrypted_hash: str
) -> dict:
    try:
        agent_map: Dict[str, any] = {w.uid(): w for w in wrapped_agents}
        agents_out = []
        certs_out = {}

        for node in _walk_nodes(template_directive):
            uid = node.get("universal_id")
            if not uid:
                continue
            wrapper = agent_map.get(uid)
            if not wrapper:
                continue

            conn = wrapper.get_connection_snapshot() or {}
            agents_out.append({
                "universal_id": uid,
                "name": wrapper.name(),
                "serial": wrapper.get_serial(),
                "security-tag": wrapper.get_security_tag() or node.get("security-tag"),
                "connection": {
                    **({"proto":  conn.get("proto")}  if conn.get("proto")  else {}),
                    **({"host":   conn.get("host")}   if conn.get("host")   else {}),
                    **({"port":   conn.get("port")}   if conn.get("port")   else {}),
                    **({"serial": conn.get("serial")} if conn.get("serial") else {}),
                    **({"channel": conn.get("default_channel")} if conn.get("default_channel") else {})

                }
            })

            wrapper.get_connection() or {}
            signing = wrapper.get_signing() or {}

            entry = {}

            entry["connection_cert"] = wrapper.get_connection_cert() or {}


            if signing:
                entry["signing"] = {
                    **({"remote_pubkey": signing.get("remote_pubkey")} if signing.get("remote_pubkey") else {}),
                    **({"remote_privkey": signing.get("remote_privkey")} if signing.get("remote_privkey") else {}),
                    **({"pubkey": signing.get("pubkey")} if signing.get("pubkey") else {}),
                    **({"privkey":       signing.get("privkey")}       if signing.get("privkey") else {}),
                    **({"serial":        signing.get("serial")}        if signing.get("serial") else {})
                }

            symmetric = wrapper.get_symmetric_encryption() or {}

            if symmetric:

                entry["symmetric_encryption"] = {
                    **({"key": symmetric.get("key")} if symmetric.get("key") else {}),
                    **({"type": symmetric.get("type")} if symmetric.get("type") else {}),
                    **({"created_at": symmetric.get("created_at")} if symmetric.get("created_at") else {})
                }

            if entry:
                certs_out[uid] = entry

        return {
            "label": label,
            "source_directive": source_directive_id,
            "deployed_at": datetime.now().isoformat(),
            "swarm_key": aes_key_b64,
            "encrypted_path": encrypted_path,
            "encrypted_hash": encrypted_hash,
            "agents": agents_out,
            "certs": certs_out
        }

    except Exception as e:
        emit_gui_exception_log("PhoenixControlPanel.mint_deployment_metadata", e)
        return {}
