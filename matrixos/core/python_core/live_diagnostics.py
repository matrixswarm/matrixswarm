"""Fixed, bounded diagnostic reads for the signed Phoenix session transport.

No caller selects a universe, path, command, credential, or archived boot.
The calling agent supplies its own runtime directory. Filesystem permissions
remain unchanged; unreadable evidence stays an explicit coverage limit.
"""
from datetime import datetime, timezone
from pathlib import Path
import json

from core.python_core.swarm_diagnostics import BOOT, IDENTIFIER, identifier, agents_snapshot, log_snapshot
from core.python_core.swarm_processes import get_all_swarm_agent_info

MAX_RESPONSE = 384 * 1024


class DiagnosticSnapshotError(ValueError):
    """A fixed failure code safe to return without paths or exception text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def tree_snapshot(root, boot):
    """Matrix projects identities/relationships only, never config or vaults."""
    result = {"runtime_id": boot, "state": "unavailable", "nodes": [],
              "observed_at": datetime.now(timezone.utc).isoformat(), "truncated": False}
    if not isinstance(root, dict):
        return result
    stack, seen = [(root, None)], set()
    try:
        while stack and len(result["nodes"]) < 256:
            node, parent = stack.pop()
            uid = identifier(node.get("universal_id"))
            children = node.get("children", [])
            if uid in seen or not isinstance(children, list):
                raise ValueError("Invalid tree")
            seen.add(uid)
            name = node.get("name")
            if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
                name = uid
            result["nodes"].append({"agent_id": uid, "parent_id": parent, "name": name})
            if len(children) > 256:
                raise ValueError("Invalid tree")
            stack.extend((child, uid) for child in reversed(children))
        result.update(state="available", truncated=bool(stack))
    except (ValueError, TypeError, AttributeError):
        result.update(state="unavailable", nodes=[], truncated=False)
    return result


def session_snapshot(comm_path, operation, runtime_id, agent_id=None, tree=None):
    comm = Path(comm_path)
    boot, universe = comm.parent.name, comm.parent.parent.name
    if (comm.name != "comm" or comm.parents[2].name != "runtime"
            or comm.parents[3].name != "universes" or not BOOT.fullmatch(boot)):
        raise DiagnosticSnapshotError("INVALID_LOCAL_RUNTIME")
    identifier(universe)
    if operation not in {"bind", "agents", "logs", "inspect"}:
        raise DiagnosticSnapshotError("UNSUPPORTED_DIAGNOSTIC_OPERATION")
    if (operation == "bind" and runtime_id != "") or (operation != "bind" and runtime_id != boot):
        raise DiagnosticSnapshotError("RUNTIME_CHANGED")
    base = str(comm.parents[4])
    infos = get_all_swarm_agent_info(universe, base=base)
    boots = {row.get("reboot_uuid") for row in infos}
    if boots != {boot}:
        raise DiagnosticSnapshotError("BOOT_UNAVAILABLE_OR_AMBIGUOUS")
    if operation == "bind":
        return {"version": 1, "universe": universe, "boot_id": boot,
                "observed_at": datetime.now(timezone.utc).isoformat()}
    if operation == "logs":
        identifier(agent_id)
        if agent_id not in {row["universal_id"] for row in infos}:
            raise DiagnosticSnapshotError("AGENT_NOT_OBSERVED")
        document = log_snapshot(universe, agent_id, infos, base=base)
    else:
        document = agents_snapshot(universe, infos, base=base)
        document["boot_id"] = boot
        if not isinstance(tree, dict) or tree.get("runtime_id") != boot:
            raise DiagnosticSnapshotError("TREE_RUNTIME_MISMATCH")
        document["agent_tree_snapshot"] = tree
        if operation == "inspect":
            ids = sorted({row["agent_id"] for row in document["agents"]})
            document["logs"] = [log_snapshot(universe, uid, infos, base=base,
                                  max_bytes=4096, include_progress=False) for uid in ids[:64]]
            document["logs_truncated"] = len(ids) > 64
            while len(json.dumps(document).encode("utf-8")) > MAX_RESPONSE and document["logs"]:
                document["logs"].pop()
                document["logs_truncated"] = True
    if len(json.dumps(document).encode("utf-8")) > MAX_RESPONSE:
        raise DiagnosticSnapshotError("RESPONSE_LIMIT_EXCEEDED")
    return document
