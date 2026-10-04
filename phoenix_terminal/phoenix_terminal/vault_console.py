"""Operator-only, headless inventory session using the existing Phoenix vault format.

This first adapter exposes no credentials, live connections, writes, or deployment
execution. The HTTP worker retains only an allowlisted public projection.
"""
from __future__ import annotations

from copy import deepcopy
import getpass
import importlib
import json
from pathlib import Path
import sys
import threading
import time
import warnings

from .bridge.deployment_view import agent_nodes
from .bridge.permissions import describe_operations, validate_call
from .bridge.sanitize import redact_log_line
from .bridge.server import BridgeServer


READ_OPERATIONS = frozenset({"bridge.status", "tools.describe", "deployment.list", "agent.list", "agent.describe"})
HELP = """Operator vault console (read-only inventory milestone)
  deployments            List public prepared deployment IDs; no credentials.
  select ID [ID ...]      Replace the selection. Revokes any enabled endpoint.
  enable [SECONDS]       Confirm publication; default 900s, maximum 3600s.
  status                 Show selection/access state without secrets.
  lock / quit            Revoke access, discard inventory, and exit.
  help                   Show this contract.

Agent client: phoenixctl bridge describe, deployments, agents ID, agent ID AGENT_ID.
No auto-connect, deploy, restart, configuration edits, evidence reads, or vault writes.
Permission/credential edits in a GUI require closing and reopening this snapshot.
If unlock fails: check the path/credential in Phoenix; do not paste secrets to an LLM.
If enable fails: disable another endpoint using this same data directory first.
Missing Linux icons are cosmetic; this console uses plain text and escaped JSON.
"""


def _identifier(value):
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Vault contains an invalid public identity; correct it in Phoenix.")
    return value


def _text(value):
    # Imported metadata must never smuggle a credential-bearing object through
    # a field which is supposed to be a name. Do not echo arbitrary structures.
    if not isinstance(value, str):
        return None
    return redact_log_line("".join(c for c in value if ord(c) >= 32 and ord(c) != 127), max_chars=256)


def public_inventory(data):
    deployments = data.get("deployments", {})
    if not isinstance(deployments, dict) or len(deployments) > 1024:
        raise ValueError("Vault deployment inventory is invalid or too large.")
    result = {}
    for deployment_id, deployment in deployments.items():
        _identifier(deployment_id)
        if not isinstance(deployment, dict):
            raise ValueError("Vault contains an invalid deployment; correct it in Phoenix.")
        agents = {}
        for agent in agent_nodes(deployment.get("agents", [])):
            uid = _identifier(agent.get("universal_id"))
            if uid in agents:
                raise ValueError("Vault contains duplicate agent identities; correct it in Phoenix.")
            agents[uid] = {"universal_id": uid, "name": _text(agent.get("name")), "app": _text(agent.get("app"))}
        result[deployment_id] = {
            "deployment": {"id": deployment_id, "label": _text(deployment.get("label", deployment_id)),
                           "name": _text(deployment.get("name", deployment_id)), "agent_count": len(agents)},
            "agents": agents,
        }
    return result


def load_vault_data(phoenix_root, vault_path, password):
    """Reuse Phoenix decryption without loading Qt, global state, or GUI hooks."""
    root = Path(phoenix_root).resolve()
    expected = root / "matrix_gui/modules/vault/crypto/vault_handler.py"
    if not expected.is_file() or not (root / "phoenix.py").is_file():
        raise ValueError("Not a recognized Phoenix source directory.")
    path = Path(vault_path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Vault must be a regular file smaller than 64 MiB.")
    sys.path.insert(0, str(root))
    try:
        handler = importlib.import_module("matrix_gui.modules.vault.crypto.vault_handler")
        if Path(handler.__file__).resolve() != expected:
            raise RuntimeError("A different Phoenix source is already loaded. Start a fresh terminal process.")
        data = handler.load_vault_singlefile(password, str(path))
        if not isinstance(data, dict):
            raise ValueError("Vault could not be unlocked. Check its credential and integrity in Phoenix.")
        return data
    finally:
        sys.path.pop(0)


def load_inventory(phoenix_root, vault_path, password):
    """Decrypt only long enough to construct the credential-free inventory."""
    return public_inventory(load_vault_data(phoenix_root, vault_path, password))


class InventoryAccess:
    """Immutable public snapshot with a fixed lifetime and immediate revocation."""
    def __init__(self, inventory, deployment_ids, lifetime, clock=time.monotonic):
        if type(lifetime) is not int or not 60 <= lifetime <= 3600:
            raise ValueError("Access lifetime must be an integer from 60 to 3600 seconds.")
        if not deployment_ids or len(set(deployment_ids)) != len(deployment_ids) or any(i not in inventory for i in deployment_ids):
            raise ValueError("Select one or more distinct current deployment IDs.")
        self._inventory = deepcopy({i: inventory[i] for i in deployment_ids})
        self._clock = clock
        self._deadline = clock() + lifetime
        self._lock = threading.RLock()

    def revoke(self):
        with self._lock:
            self._inventory.clear()

    def handle(self, method, params):
        with self._lock:
            if self._clock() >= self._deadline:
                self._inventory.clear()
            if not self._inventory:
                raise PermissionError("Inventory access is closed or expired. Ask the operator to enable a new session.")
            if method not in READ_OPERATIONS:
                raise PermissionError("Unavailable in headless inventory mode. No remote actions or vault writes are permitted.")
            validate_call(method, params)
            if method == "bridge.status":
                return {"mode": "headless_inventory", "read_only": True, "assignment_active": True,
                        "remaining_seconds": max(0, int(self._deadline - self._clock())),
                        "deployment_count": len(self._inventory)}
            if method == "tools.describe":
                descriptions = {"agent.describe": "Read public agent identity only; no configuration or actions.",
                                "agent.list": "Read the operator-selected saved inventory, not live health.",
                                "deployment.list": "Read explicitly selected prepared deployments, not server state."}
                tools = [item for item in describe_operations() if item["name"] in READ_OPERATIONS]
                for item in tools:
                    item["description"] = descriptions.get(item["name"], item["description"])
                return {"mode": "headless_inventory", "tools": tools, "remote_actions_available": False}
            if method == "deployment.list":
                return {"deployments": deepcopy([item["deployment"] for item in self._inventory.values()])}
            deployment = self._inventory.get(params["deployment_id"])
            if deployment is None:
                raise PermissionError("Deployment is outside this assignment. Use the exact returned ID.")
            if method == "agent.list":
                return {"agents": deepcopy(list(deployment["agents"].values()))}
            agent = deployment["agents"].get(params["agent_id"])
            if agent is None:
                raise PermissionError("Agent is outside this assignment.")
            return {"agent": deepcopy(agent), "actions": [], "hint": "Prepared inventory only; no live health or credential access."}


class OperatorSession:
    def __init__(self, inventory, data_dir):
        self.inventory = inventory
        self.data_dir = data_dir
        self.selected = []
        self._access = self._server = self._timer = None
        self._lock = threading.RLock()

    def disable(self):
        with self._lock:
            if self._access:
                self._access.revoke()
            if self._timer:
                self._timer.cancel()
            try:
                if self._server:
                    self._server.stop()
            finally:
                self._access = self._server = self._timer = None

    def select(self, ids):
        # Validate before replacing existing scope; invalid input grants nothing.
        if not ids or len(set(ids)) != len(ids) or any(i not in self.inventory for i in ids):
            raise ValueError("Use distinct deployment IDs from deployments.")
        self.disable()
        self.selected = list(ids)

    def enable(self, seconds=900):
        with self._lock:
            self.disable()
            access = InventoryAccess(self.inventory, self.selected, seconds)
            server = BridgeServer(access.handle, self.data_dir)
            try:
                server.start()
            except Exception:
                access.revoke()
                server.stop()
                raise
            self._access, self._server = access, server
            self._timer = threading.Timer(seconds, self._expire, args=(access,))
            self._timer.daemon = True
            self._timer.start()

    def _expire(self, access):
        # A canceled timer may already be waiting for the lock. It must never
        # revoke a newer assignment which has replaced its original scope.
        with self._lock:
            if self._access is access:
                self.disable()

    def close(self):
        try:
            self.disable()
        finally:
            self.inventory.clear()
            self.selected.clear()


def run_console(phoenix_root, vault_path, data_dir):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError("Operator vault opening requires a private interactive terminal; piped credentials are refused.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Phoenix vault password (operator only): ")
    except getpass.GetPassWarning:
        raise RuntimeError("Hidden password entry is unavailable; vault was not opened.") from None
    try:
        inventory = load_inventory(phoenix_root, vault_path, password)
    finally:
        password = None  # Drop our reference; Python cannot promise memory zeroization.
    session = OperatorSession(inventory, data_dir)
    try:
        print(HELP)
        print("Vault decrypted for public inventory. Agent access is OFF; no credentials retained by the endpoint.")
        while True:
            words = input("phoenix-operator> ").split()
            if not words:
                continue
            command, *args = words
            try:
                if command in {"lock", "quit", "exit"} and not args:
                    break
                if command == "help" and not args:
                    print(HELP)
                elif command == "deployments" and not args:
                    print(json.dumps([i["deployment"] for i in inventory.values()], indent=2, ensure_ascii=True))
                elif command == "select":
                    session.select(args)
                    print("Selection saved for this session; access is OFF.")
                elif command == "enable" and len(args) <= 1:
                    seconds = int(args[0]) if args else 900
                    if not 60 <= seconds <= 3600 or not session.selected:
                        raise ValueError("Select deployments first; lifetime must be 60 to 3600 seconds.")
                    print("Expose ONLY read-only inventory for these deployments: " + json.dumps(session.selected, ensure_ascii=True))
                    if input(f"Enable for {seconds}s? Type ENABLE to confirm: ") == "ENABLE":
                        session.enable(seconds)
                        print("Inventory endpoint enabled. Use phoenixctl bridge describe from the agent terminal.")
                    else:
                        print("Not enabled.")
                elif command == "status" and not args:
                    with session._lock:
                        print(json.dumps({"selected": session.selected, "enabled": session._access is not None,
                                          "mode": "read_only_inventory"}, ensure_ascii=True))
                else:
                    print("Unknown command or arguments. Use help; no shell execution is available.")
            except (ValueError, RuntimeError, OSError) as exc:
                print("Operator request rejected: " + json.dumps(str(exc), ensure_ascii=True))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        session.close()
    print("Locked. Endpoint revoked and public inventory discarded.")
    return 0
