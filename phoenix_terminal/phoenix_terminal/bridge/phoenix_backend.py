"""Phoenix-backed tool implementation. This module runs inside the cockpit."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .sanitize import public_agent, public_deployment, redact_log_line


TOOLS = {
    "bridge.status": "Report bridge, vault, and active-session state.",
    "deployment.list": "List redacted deployments from the currently unlocked Phoenix vault.",
    "deployment.launch": "Ask the human in Phoenix to open a deployment session.",
    "session.list": "List active Phoenix deployment sessions.",
    "agent.list": "List redacted agents in one vault deployment.",
    "agent.tree": "Read the redacted live agent tree from one active Phoenix session.",
    "agent.logs.start": "Request logs for one agent through the active Phoenix session.",
    "agent.logs.read": "Read buffered, redacted lines from a log subscription.",
}


class PhoenixBackend:
    def __init__(self, cockpit: object, event_bus: object, vault_core: object):
        self._cockpit = cockpit
        self._event_bus = event_bus
        self._vault_core = vault_core
        self._vault_unlocked = False
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._live_trees: dict[str, dict[str, Any]] = {}
        event_bus.on("vault.unlocked", self._on_vault_unlocked)
        event_bus.on("vault.closed", self._on_vault_closed)

    def close(self) -> None:
        self._event_bus.off("vault.unlocked", self._on_vault_unlocked)
        self._event_bus.off("vault.closed", self._on_vault_closed)
        self._subscriptions.clear()
        self._live_trees.clear()

    def disable_bridge(self) -> None:
        """Revoke all capabilities that were issued while the bridge was on."""
        self._subscriptions.clear()
        self._live_trees.clear()

    @property
    def vault_unlocked(self) -> bool:
        return self._vault_unlocked

    def _on_vault_unlocked(self, **_kwargs: object) -> None:
        self._vault_unlocked = True

    def _on_vault_closed(self, **_kwargs: object) -> None:
        self._vault_unlocked = False
        self._subscriptions.clear()
        self._live_trees.clear()

    def _vault(self) -> object:
        if not self._vault_unlocked:
            raise RuntimeError("Phoenix vault is locked; unlock it in the Phoenix GUI")
        return self._vault_core.get()

    def _resolve_deployment(self, deployment_ref: str) -> tuple[str, dict[str, Any]]:
        if not deployment_ref:
            raise ValueError("deployment_id is required")
        deployments = self._vault().snapshot("deployments")
        if not isinstance(deployments, dict):
            deployments = {}

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
        if not session_ref:
            raise ValueError("session_id is required")

        # A runtime session UUID is always authoritative.
        session = next(
            (item for item in self._cockpit.session_processes if str(item.get("session_id", "")) == session_ref),
            None,
        )
        if session is not None:
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
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"more than one session matches '{session_ref}'; use the runtime session id")
        raise ValueError(f"session '{session_ref}' is not active in Phoenix")

    def handle(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "tools.describe":
            return {"tools": [{"name": name, "description": description} for name, description in TOOLS.items()]}
        if method == "bridge.status":
            return self.status()
        if method == "deployment.list":
            return self.list_deployments()
        if method == "deployment.launch":
            return self.launch_deployment(str(params.get("deployment_id", "")))
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

    def status(self) -> dict[str, Any]:
        return {
            "bridge": "ready",
            "vault": "unlocked" if self._vault_unlocked else "locked",
            "active_sessions": len(self._cockpit.session_processes),
            "capabilities": sorted(TOOLS),
        }

    def list_deployments(self) -> dict[str, Any]:
        deployments = self._vault().snapshot("deployments")
        public = [
            public_deployment(deployment_id, deployment)
            for deployment_id, deployment in sorted(deployments.items())
            if isinstance(deployment, dict)
        ]
        return {"deployments": public}

    def list_sessions(self) -> dict[str, Any]:
        sessions = []
        for item in self._cockpit.session_processes:
            process = item.get("proc")
            sessions.append({
                "session_id": item.get("session_id"),
                "deployment_id": item.get("deployment_id", item.get("session_id")),
                "state": "running" if process is not None and process.is_alive() else "stopped",
            })
        return {"sessions": sessions}

    def list_agents(self, deployment_id: str) -> dict[str, Any]:
        deployment_id, deployment = self._resolve_deployment(deployment_id)
        agents = deployment.get("agents") if isinstance(deployment.get("agents"), list) else []
        return {
            "deployment_id": deployment_id,
            "agents": [public_agent(agent) for agent in agents if isinstance(agent, dict)],
        }

    def launch_deployment(self, deployment_id: str) -> dict[str, Any]:
        deployment_id, deployment = self._resolve_deployment(deployment_id)
        existing = next(
            (item for item in self._cockpit.session_processes if item.get("deployment_id", item.get("session_id")) == deployment_id),
            None,
        )
        if existing is not None:
            return {"state": "already_active", "session_id": existing.get("session_id"), "deployment_id": deployment_id}

        from PyQt6.QtWidgets import QMessageBox

        label = deployment.get("label", deployment_id)
        answer = QMessageBox.question(
            self._cockpit,
            "LLM requested Phoenix connection",
            f"Allow the local LLM bridge to open the Phoenix deployment session '{label}'?\n\n"
            "Phoenix will retain control of credentials, signing, encryption, and connections.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return {"state": "denied", "deployment_id": deployment_id}

        self._cockpit.launch_session(deployment_id, deployment, None)
        active = next(
            (item for item in self._cockpit.session_processes if item.get("session_id") == deployment_id),
            None,
        )
        if active is None:
            return {"state": "failed", "deployment_id": deployment_id, "reason": "Phoenix session did not become active"}
        active["deployment_id"] = deployment_id
        return {"state": "active", "session_id": deployment_id, "deployment_id": deployment_id}

    def start_agent_logs(self, session_id: str, agent_id: str, follow: bool) -> dict[str, Any]:
        session = self._session(session_id)
        runtime_session_id = str(session.get("session_id"))
        deployment_id = str(session.get("deployment_id", runtime_session_id))
        agents = self.list_agents(deployment_id)["agents"]
        if not any(agent.get("universal_id") == agent_id for agent in agents):
            raise ValueError(f"agent '{agent_id}' is not part of deployment '{deployment_id}'")

        subscription_id = uuid.uuid4().hex
        self._subscriptions[subscription_id] = {
            "session_id": runtime_session_id,
            "deployment_id": deployment_id,
            "agent_id": agent_id,
            "created_at": int(time.time()),
            "state": "starting",
            "lines": [],
        }
        session["conn"].send({
            "type": "bridge.fetch_logs",
            "session_id": runtime_session_id,
            "agent_id": agent_id,
            "subscription_id": subscription_id,
            "follow": follow,
        })
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
        after = max(0, after)
        limit = max(1, min(limit, 200))
        lines = subscription["lines"][after:after + limit]
        return {
            "subscription_id": subscription_id,
            "state": subscription["state"],
            "agent_id": subscription["agent_id"],
            "lines": lines,
            "next_cursor": after + len(lines),
            "buffered_lines": len(subscription["lines"]),
        }

    def handle_session_message(self, message: dict[str, Any]) -> bool:
        message_type = message.get("type")
        if message_type == "bridge.agent_tree":
            session_id = str(message.get("session_id", ""))
            agents = message.get("agents") if isinstance(message.get("agents"), list) else []
            self._live_trees[session_id] = {
                "updated_at": int(time.time()),
                "agents": [public_agent(agent) for agent in agents if isinstance(agent, dict)],
            }
            return True
        if message_type not in {"bridge.log.started", "bridge.log", "bridge.log.error"}:
            return False
        subscription_id = message.get("subscription_id")
        subscription = self._subscriptions.get(subscription_id)
        if subscription is None:
            return True
        if message_type == "bridge.log.started":
            subscription["state"] = "following" if message.get("follow") else "waiting"
        elif message_type == "bridge.log.error":
            subscription["state"] = "error"
            subscription["lines"].append(redact_log_line(f"[bridge] {message.get('error', 'log request failed')}"))
        else:
            new_lines = message.get("lines") if isinstance(message.get("lines"), list) else []
            subscription["lines"].extend(redact_log_line(line) for line in new_lines[:500])
            if len(subscription["lines"]) > 2000:
                subscription["lines"] = subscription["lines"][-2000:]
            subscription["state"] = "following" if message.get("follow", True) else "complete"
        return True
