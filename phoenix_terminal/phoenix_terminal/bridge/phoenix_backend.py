"""Phoenix-backed tool implementation. This module runs inside the cockpit."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .actions import AssignmentActions
from .investigations import Investigations
from .deployment_view import agent_nodes, configured_agent
from .permissions import CursorBuffer, config_surface, describe_operations, validate_call
from .sanitize import public_agent, public_deployment, redact_log_line


class PhoenixBackend(AssignmentActions, Investigations):
    def __init__(self, cockpit: object, event_bus: object, vault_core: object):
        self._cockpit = cockpit
        self._event_bus = event_bus
        self._vault_core = vault_core
        self._vault_unlocked = False
        self._assignment_id = None
        self._scope = {}
        self._actions = {}
        self._alerts = {}
        self._alert_sources = {}
        self._investigation_bindings = {}
        self._review_receipts = {}
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._live_trees: dict[str, dict[str, Any]] = {}
        event_bus.on("vault.unlocked", self._on_vault_unlocked)
        event_bus.on("vault.closed", self._on_vault_closed)

    def close(self) -> None:
        self._event_bus.off("vault.unlocked", self._on_vault_unlocked)
        self._event_bus.off("vault.closed", self._on_vault_closed)
        self.disable_bridge()

    def disable_bridge(self) -> None:
        """Revoke all capabilities that were issued while the bridge was on."""
        if self._assignment_id:
            for session in self._cockpit.session_processes:
                if str(session.get("deployment_id", session.get("session_id"))) in self._scope:
                    try:
                        session["conn"].send({"type": "bridge.revoke"})
                    except (OSError, EOFError):
                        pass
        self._subscriptions.clear()
        self._live_trees.clear()
        self._alerts.clear()
        self._alert_sources.clear()
        self._investigation_bindings.clear()
        self._review_receipts.clear()
        self._actions.clear()
        self._scope.clear()
        self._assignment_id = None

    @property
    def vault_unlocked(self) -> bool:
        return self._vault_unlocked

    def _on_vault_unlocked(self, **_kwargs: object) -> None:
        self.disable_bridge()
        self._vault_unlocked = True

    def _on_vault_closed(self, **_kwargs: object) -> None:
        self._vault_unlocked = False
        self.disable_bridge()

    def available_assignments(self):
        """Operator UI only: current vault deployment identities."""
        return [public_deployment(str(key), value)
                for key, value in self._vault().snapshot("deployments").items()
                if isinstance(value, dict)]

    def enable_assignment(self, deployment_ids):
        """Operator UI only; freeze the selected deployment and agent inventory."""
        deployments = self._vault().snapshot("deployments")
        if not deployment_ids or any(key not in deployments for key in deployment_ids):
            raise ValueError("Select at least one current vault deployment.")
        scope = {}
        for key in deployment_ids:
            agents = agent_nodes(deployments[key].get("agents", []))
            uids = [a.get("universal_id") for a in agents if isinstance(a, dict)]
            if any(not isinstance(uid, str) or not uid for uid in uids) or len(set(uids)) != len(uids):
                raise ValueError("Selected deployment has invalid or duplicate agent identities.")
            scope[key] = frozenset(uids)
        self.disable_bridge()
        self._scope = scope
        self._assignment_id = uuid.uuid4().hex

    def _require_assignment(self):
        if not self._vault_unlocked or not self._assignment_id:
            raise PermissionError("No active assignment. Ask the operator to unlock a vault and enable terminal access.")

    def _agent(self, deployment_id, agent_id):
        dep_id, deployment = self._resolve_deployment(deployment_id)
        if agent_id not in self._scope[dep_id]:
            raise ValueError("Agent is outside this assignment.")
        matches = [a for a in agent_nodes(deployment.get("agents", []))
                   if isinstance(a, dict) and a.get("universal_id") == agent_id]
        if len(matches) != 1:
            raise ValueError("Assigned agent is unavailable or ambiguous.")
        return matches[0]

    def describe_agent(self, deployment_id, agent_id):
        agent = self._agent(deployment_id, agent_id)
        _, deployment = self._resolve_deployment(deployment_id)
        if config_surface(agent)["fields"]:
            surface = config_surface(configured_agent(deployment, agent_id))
        else:
            surface = config_surface(agent)
        return {"agent": public_agent(agent), "configuration": surface,
                "actions": ["agent.logs.start", "agent.restart", "agent.config.set"]
                if surface["fields"] else ["agent.logs.start", "agent.restart"],
                "hint": "Mutations require an operator decision. Credentials are managed by Phoenix."}

    def _vault(self) -> object:
        if not self._vault_unlocked:
            raise RuntimeError("Phoenix vault is locked; unlock it in the Phoenix GUI")
        return self._vault_core.get()

    def _resolve_deployment(self, deployment_ref: str) -> tuple[str, dict[str, Any]]:
        self._require_assignment()
        if not deployment_ref:
            raise ValueError("deployment_id is required")
        deployments = self._vault().snapshot("deployments")
        if not isinstance(deployments, dict):
            deployments = {}

        deployments = {k: v for k, v in deployments.items() if k in self._scope}
        exact = deployments.get(deployment_ref)
        if isinstance(exact, dict) and exact:
            return deployment_ref, exact

        wanted = deployment_ref.casefold()
        matches: list[tuple[str, dict[str, Any]]] = []
        for deployment_id, deployment in deployments.items():
            if not isinstance(deployment, dict) or not deployment:
                continue
            aliases = {
                str(deployment_id),
                str(deployment.get("id", "")),
                str(deployment.get("label", "")),
                str(deployment.get("name", "")),
            }
            if wanted in {alias.casefold() for alias in aliases if alias}:
                matches.append((str(deployment_id), deployment))

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"deployment reference '{deployment_ref}' is ambiguous; use its vault id")
        raise ValueError(f"deployment '{deployment_ref}' was not found in the unlocked vault")

    def _deployment(self, deployment_ref: str) -> dict[str, Any]:
        return self._resolve_deployment(deployment_ref)[1]

    def _session(self, session_ref: str) -> dict[str, Any]:
        self._require_assignment()
        if not session_ref:
            raise ValueError("session_id is required")

        # A runtime session UUID is always authoritative.
        session = next(
            (item for item in self._cockpit.session_processes if str(item.get("session_id", "")) == session_ref),
            None,
        )
        if session is not None:
            self._resolve_deployment(str(session.get("deployment_id", session["session_id"])))
            return session

        # Human-facing commands may use the vault id, label, or name printed by
        # deployment.list. Resolve those aliases before matching the live session.
        try:
            deployment_id, _deployment = self._resolve_deployment(session_ref)
        except ValueError:
            deployment_id = session_ref
        matches = [
            item
            for item in self._cockpit.session_processes
            if str(item.get("deployment_id", "")).casefold() == deployment_id.casefold()
            or str(item.get("deployment_label", "")).casefold() == session_ref.casefold()
        ]
        if len(matches) == 1:
            self._resolve_deployment(str(matches[0].get("deployment_id", matches[0]["session_id"])))
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"more than one session matches '{session_ref}'; use the runtime session id")
        raise ValueError(f"session '{session_ref}' is not active in Phoenix")

    def handle(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        validate_call(method, params)
        if method == "tools.describe":
            return {"tools": describe_operations()}
        if method == "bridge.status":
            return self.status()
        self._require_assignment()
        if method.startswith("investigation."):
            return self.handle_investigation(method, params)
        if method in {"deployment.launch", "agent.restart", "agent.config.set"}:
            return self.request_action(method, {**params, "request_id": params.get("request_id") or uuid.uuid4().hex})
        if method == "action.status":
            return self.action_status(params["request_id"])
        if method == "agent.describe":
            return self.describe_agent(params["deployment_id"], params["agent_id"])
        if method == "session.alerts":
            session = self._session(params["session_id"])
            result = self._alert_buffer(session).read(params.get("after", 0), params.get("limit", 100))
            result["hint"] = "Alerts cover this assignment session only; gaps are explicit."
            return result
        if method == "deployment.list":
            return self.list_deployments()
        if method == "session.list":
            return self.list_sessions()
        if method == "agent.list":
            return self.list_agents(str(params.get("deployment_id", "")))
        if method == "agent.tree":
            return self.agent_tree(str(params.get("session_id", "")), bool(params.get("refresh", True)))
        if method == "agent.logs.start":
            return self.start_agent_logs(
                str(params.get("session_id", "")),
                str(params.get("agent_id", "")),
                bool(params.get("follow", True)),
            )
        if method == "agent.logs.read":
            return self.read_agent_logs(
                str(params.get("subscription_id", "")),
                int(params.get("after", 0)),
                int(params.get("limit", 100)),
            )
        raise ValueError(f"unknown or unavailable bridge method: {method}")

    def status(self):
        enabled = bool(self._assignment_id and self._vault_unlocked)
        return {"bridge": "ready" if enabled else "disabled",
                "vault": "unlocked" if self._vault_unlocked else "locked",
                "assignment_id": self._assignment_id,
                "active_sessions": len(self.list_sessions()["sessions"]) if enabled else 0,
                "capabilities": [op["name"] for op in describe_operations()],
                "hint": "Run tools.describe, then deployment.list. Approval is available only in the operator's Phoenix window."}

    def list_deployments(self):
        self._require_assignment()
        return {"deployments": [public_deployment(key, dep) for key, dep in
                sorted(self._vault().snapshot("deployments").items())
                if key in self._scope and isinstance(dep, dict)]}

    def list_sessions(self):
        self._require_assignment()
        current = self._vault().snapshot("deployments")
        sessions = []
        for item in self._cockpit.session_processes:
            dep_id = str(item.get("deployment_id", item.get("session_id")))
            if dep_id not in self._scope or dep_id not in current:
                continue
            process = item.get("proc")
            sessions.append({"session_id": item.get("session_id"), "deployment_id": dep_id,
                             "state": "running" if process is not None and process.is_alive() else "stopped"})
        return {"sessions": sessions}

    def list_agents(self, deployment_id):
        dep_id, deployment = self._resolve_deployment(deployment_id)
        return {"deployment_id": dep_id, "agents": [
            public_agent(a) for a in agent_nodes(deployment.get("agents", []))
            if isinstance(a, dict) and a.get("universal_id") in self._scope[dep_id]]}

    def _open_deployment(self, deployment_id, deployment):
        """Called only after an exact operator-approved action is consumed."""
        existing = next((s for s in self._cockpit.session_processes
                         if s.get("deployment_id", s.get("session_id")) == deployment_id
                         and s.get("proc") is not None and s["proc"].is_alive()), None)
        if existing is not None:
            return {"state": "already_active", "session_id": existing["session_id"]}
        self._cockpit.launch_session(deployment_id, deployment, None)
        active = next((s for s in self._cockpit.session_processes
                       if s.get("session_id") == deployment_id), None)
        if active is None:
            return {"state": "uncertain", "hint": "Session did not become active. Inspect Phoenix before retrying."}
        active["deployment_id"] = deployment_id
        return {"state": "active", "session_id": active["session_id"]}

    def start_agent_logs(self, session_id: str, agent_id: str, follow: bool) -> dict[str, Any]:
        session = self._session(session_id)
        runtime_session_id = str(session.get("session_id"))
        deployment_id = str(session.get("deployment_id", runtime_session_id))
        agents = self.list_agents(deployment_id)["agents"]
        if not any(agent.get("universal_id") == agent_id for agent in agents):
            raise ValueError(f"agent '{agent_id}' is not part of deployment '{deployment_id}'")

        if len(self._subscriptions) >= 64:
            raise ValueError("Log subscription limit reached. Reopen the assignment to release subscriptions.")
        subscription_id = uuid.uuid4().hex
        self._subscriptions[subscription_id] = {
            "session_id": runtime_session_id,
            "deployment_id": deployment_id,
            "agent_id": agent_id,
            "created_at": int(time.time()),
            "state": "starting",
            "buffer": CursorBuffer(),
        }
        try:
            session["conn"].send({
                "type": "bridge.fetch_logs",
                "session_id": runtime_session_id,
                "agent_id": agent_id,
                "subscription_id": subscription_id,
                "follow": follow,
            })
        except Exception:
            self._subscriptions.pop(subscription_id, None)
            raise

        return {
            "state": "starting",
            "subscription_id": subscription_id,
            "session_id": runtime_session_id,
            "deployment_id": deployment_id,
            "agent_id": agent_id,
        }

    def agent_tree(self, session_id: str, refresh: bool) -> dict[str, Any]:
        session = self._session(session_id)
        runtime_session_id = str(session.get("session_id"))
        cached = self._live_trees.get(runtime_session_id)
        if refresh or cached is None:
            session["conn"].send({"type": "bridge.agent_tree", "session_id": runtime_session_id})
        if cached is None:
            return {"session_id": runtime_session_id, "state": "refreshing", "agents": []}
        return {
            "session_id": runtime_session_id,
            "state": "refreshing" if refresh else "ready",
            "updated_at": cached["updated_at"],
            "agents": cached["agents"],
        }

    def read_agent_logs(self, subscription_id: str, after: int, limit: int) -> dict[str, Any]:
        subscription = self._subscriptions.get(subscription_id)
        if subscription is None:
            raise ValueError("log subscription was not found or the vault was closed")
        self._session(subscription["session_id"])
        page = subscription["buffer"].read(after, limit)
        return {"subscription_id": subscription_id, "state": subscription["state"],
                "agent_id": subscription["agent_id"], "lines": page.pop("items"), **page}


    def _alert_buffer(self, session):
        session_id = session["session_id"]
        source = self._alert_sources.get(session_id)
        if (source is None or source[0] is not session or source[1] is not session.get("conn")
                or source[2] is not session.get("proc")):
            self._alerts[session_id] = CursorBuffer(500)
            self._alert_sources[session_id] = (session, session.get("conn"), session.get("proc"))
        return self._alerts[session_id]

    def handle_session_message(self, message: dict[str, Any]) -> bool:
        message_type = message.get("type")
        if not self._assignment_id:
            return isinstance(message_type, str) and message_type.startswith("bridge.")
        if message_type == "swarm_feed":
            event = message.get("event", {})
            try:
                session = self._session(str(event.get("session_id", "")))
                self._alert_buffer(session).append([redact_log_line(event.get("payload", {}))])
            except (ValueError, PermissionError):
                pass
            return False
        if message_type == "bridge.action":
            action = self._actions.get(message.get("request_id"))
            if action and action["state"] == "dispatched":
                expected = action.get("runtime_session_id")
                if message.get("session_id") == expected:
                    action["result"] = {"session_dispatch": message.get("state") if message.get("state") in {"sent", "failed"} else "unknown",
                                        "hint": "Check agent status/logs for remote completion."}
            return True
        if message_type == "bridge.agent_tree":
            session_id = str(message.get("session_id", ""))
            try:
                session = self._session(session_id)
            except (ValueError, PermissionError):
                return True
            dep_id = str(session.get("deployment_id", session_id))
            agents = message.get("agents") if isinstance(message.get("agents"), list) else []
            agents = [a for a in agents if isinstance(a, dict) and a.get("universal_id") in self._scope[dep_id]]
            self._live_trees[session_id] = {
                "updated_at": int(time.time()),
                "agents": [public_agent(agent) for agent in agents if isinstance(agent, dict)],
            }
            return True
        if message_type not in {"bridge.log.started", "bridge.log", "bridge.log.error"}:
            return False
        subscription_id = message.get("subscription_id")
        subscription = self._subscriptions.get(subscription_id)
        if subscription is None or message.get("session_id") != subscription["session_id"]:
            return True
        if message_type == "bridge.log.started":
            subscription["state"] = "following" if message.get("follow") else "waiting"
        elif message_type == "bridge.log.error":
            subscription["state"] = "error"
            subscription["buffer"].append([redact_log_line(f"[bridge] {message.get('error', 'log request failed')}")])
        else:
            new_lines = message.get("lines") if isinstance(message.get("lines"), list) else []
            subscription["buffer"].append([redact_log_line(line) for line in new_lines[:500]])
            subscription["state"] = "following" if message.get("follow", True) else "complete"
        return True
