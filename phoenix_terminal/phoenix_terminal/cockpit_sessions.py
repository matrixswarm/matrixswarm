"""Narrow local cockpit adapter; approval remains owned by Terminal.

No legacy GUI action bridge, vault RPC, configuration edits or arbitrary method
forwarding. The GUI independently checks the grant and the exact vault revision
on its Qt thread before exposing sessions or opening the ordinary Connect tab.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bridge.server import BridgeServer


class CockpitSessionServer(BridgeServer):
    @property
    def connection_path(self):
        return self._data_dir / "cockpit-sessions.json"


def public_session_page(deployment_id, value):
    if (not isinstance(value, dict) or value.get("deployment_id") != deployment_id
            or value.get("state") not in {"available", "unavailable", "opened", "already_open", "uncertain"}
            or not isinstance(value.get("sessions"), list) or len(value["sessions"]) > 256):
        raise ValueError("Invalid cockpit session response")
    rows, seen = [], set()
    for item in value["sessions"]:
        if (not isinstance(item, dict) or item.get("deployment_id") != deployment_id
                or not isinstance(item.get("session_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item["session_id"])
                or item["session_id"] in seen or item.get("state") not in {"process_observed", "view_observed"}):
            raise ValueError("Invalid cockpit session identity")
        seen.add(item["session_id"])
        rows.append({"session_id": item["session_id"], "deployment_id": deployment_id,
                     "state": item["state"], "connection_health": "unknown"})
    from .swarm_inspection import session_evidence_context
    page = session_evidence_context(value, {"deployment_id": deployment_id, "state": value["state"], "sessions": rows,
            **({"session_kind": "ai_inspection", "native_agent_panels_available": False}
               if value.get("session_kind") == "ai_inspection" else {}),
            "connection_health_verified": False, "agent_health_assessed": False,
            "swarm_started": False, "swarm_started_by_this_operation": False,
            "transport_readiness_verified": False})
    readiness = value.get("connection_readiness")
    if readiness is not None:
        fields = {"state", "attempts", "max_attempts", "timeout_seconds", "ingress", "egress",
                  "http_status", "signed_reply_verified", "runtime_id", "observed_at"}
        binding = page.get("session_binding", {})
        if (value.get("session_kind") != "ai_inspection" or not isinstance(readiness, dict)
                or set(readiness) != fields or readiness.get("state") != "ready"
                or type(readiness.get("attempts")) is not int or not 1 <= readiness["attempts"] <= 3
                or type(readiness.get("max_attempts")) is not int or readiness["max_attempts"] != 3
                or type(readiness.get("timeout_seconds")) is not int or readiness["timeout_seconds"] != 50
                or type(readiness.get("http_status")) is not int or readiness["http_status"] != 200
                or readiness.get("ingress") != "wss_connected" or readiness.get("egress") != "https_accepted"
                or readiness.get("signed_reply_verified") is not True
                or readiness.get("runtime_id") != binding.get("runtime_id")
                or not isinstance(readiness.get("observed_at"), str)):
            raise ValueError("Invalid live connection readiness response")
        try:
            observed = datetime.fromisoformat(readiness["observed_at"])
            age = (datetime.now(timezone.utc) - observed).total_seconds()
            if not -10 <= age <= 120:
                raise ValueError("Stale readiness")
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Invalid live connection readiness timestamp") from None
        page["connection_readiness"] = {key: readiness[key] for key in fields}
        page["transport_readiness_verified"] = True
    return page


class CockpitSessionClient:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def call(self, method, deployment_id, identity, lease):
        if method not in {"sessions.list", "sessions.open"}:
            raise ValueError("Unavailable cockpit operation")
        if not lease():
            raise PermissionError("Connection approval ended")
        descriptor = self.data_dir / "cockpit-sessions.json"
        if not descriptor.is_file():
            return public_session_page(deployment_id, {
                "deployment_id": deployment_id, "state": "unavailable", "sessions": []})
        connection = json.loads(descriptor.read_text(encoding="utf-8"))
        if (connection.get("host") != "127.0.0.1" or type(connection.get("port")) is not int
                or not 1 <= connection["port"] <= 65535 or not isinstance(connection.get("token"), str)):
            raise ValueError("Invalid cockpit endpoint")
        request = Request(f"http://127.0.0.1:{connection['port']}/rpc", method="POST",
            data=json.dumps({"method": method, "params": {"deployment_id": deployment_id, **identity}}).encode(),
            headers={"Authorization": "Bearer " + connection["token"], "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:  # nosec B310: fixed loopback
                result = json.loads(response.read(262145))
        except HTTPError:
            # Fixed local errors only, never include a response body or token.
            if method == "sessions.open":
                return public_session_page(deployment_id, {
                    "deployment_id": deployment_id, "state": "uncertain", "sessions": []})
            raise PermissionError("Phoenix denied session access; check its unlocked Vault and Terminal policy") from None
        except (URLError, OSError):
            return public_session_page(deployment_id, {
                "deployment_id": deployment_id, "state": "unavailable" if method == "sessions.list" else "uncertain", "sessions": []})
        if not lease():
            raise PermissionError("Connection approval ended")
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ValueError("Cockpit operation did not complete")
        return public_session_page(deployment_id, result.get("result"))


class CockpitSessionBackend:
    """Only called through the Qt dispatcher, never the HTTP worker thread."""
    def __init__(self, cockpit, data_dir):
        self.cockpit = cockpit
        self.data_dir = Path(data_dir)

    def handle(self, method, params):
        from .terminal_client import call_terminal
        from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
        from matrix_gui.modules.vault.terminal_access_policy import authorize_vault_operation, vault_revision
        if method not in {"sessions.list", "sessions.open"} or not isinstance(params, dict) or set(params) != {
                "deployment_id", "request_id", "client_secret"}:
            raise PermissionError("Unavailable cockpit operation")
        dep_id = params["deployment_id"]
        if not isinstance(dep_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", dep_id):
            raise ValueError("Invalid deployment identity")
        identity = {"request_id": params["request_id"], "client_secret": params["client_secret"]}
        def authorized():
            if VaultCoreSingleton.get().access_control.ai_mode:
                raise PermissionError("AI Mode session access must use the live Phoenix gateway")
            status = call_terminal(self.data_dir, "connection.status", identity)
            resource = next((r for r in status.get("resources", []) if r.get("deployment_id") == dep_id), {})
            if status.get("state") != "approved" or method not in resource.get("operations", []):
                raise PermissionError("Terminal approval does not permit this cockpit operation")
            authority = VaultCoreSingleton.get()
            if authority._closed:
                raise PermissionError("Phoenix Vault is locked")
            vault = authority.read()
            if status.get("vault_revision") != vault_revision(vault) or not authorize_vault_operation(vault, method, dep_id):
                raise PermissionError("Phoenix and Terminal Vault revisions or permissions differ; reopen Terminal")
            return vault
        vault = authorized()
        sessions = self._sessions(dep_id)
        state = "available"
        if method == "sessions.open":
            if sessions:
                state = "already_open"
            else:
                if len(self.cockpit.session_processes) >= 64:
                    raise ValueError("Cockpit session limit reached; operator must close unused tabs")
                # Recheck immediately before Connect. No remote boot occurs.
                vault = authorized()
                deployment = dict(vault["deployments"][dep_id])
                deployment["id"] = dep_id
                import uuid
                self.cockpit.launch_session(str(uuid.uuid4()), deployment, None)
                sessions = self._sessions(dep_id)
                state = "opened" if sessions else "uncertain"
        authorized()  # Recheck before disclosing a result after slow embedding.
        return public_session_page(dep_id, {"deployment_id": dep_id, "state": state, "sessions": sessions})

    def _sessions(self, deployment_id):
        result = []
        for item in self.cockpit.session_processes:
            process = item.get("proc")
            if item.get("deployment_id") == deployment_id and process is not None and process.is_alive():
                result.append({"session_id": item["session_id"], "deployment_id": deployment_id, "state": "process_observed"})
        return result
