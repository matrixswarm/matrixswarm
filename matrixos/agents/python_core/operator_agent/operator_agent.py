"""A reusable, approval-gated cognitive agent for MCP Reflex workflows."""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Mapping
from typing import Any

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import (
    IdentityObject,
)
from core.python_core.mixin.cognitive_run import CognitiveRunError, CognitiveRunMixin
from core.python_core.mixin.encrypted_state import EncryptedStateError, EncryptedStateMixin
from core.python_core.mixin.mcp_reflex_client import (
    McpReflexClientError,
    McpReflexClientMixin,
)
from core.python_core.utils.swarm_sleep import interruptible_sleep


class Agent(EncryptedStateMixin, CognitiveRunMixin, McpReflexClientMixin, BootAgent):
    """Execute only fixed, approved workflows through MCP Reflex.

    This first cognitive-agent form intentionally has no prompt-to-tool path:
    a signed requester selects a policy-owned workflow, a distinct signed
    approver authorizes it, and only then does the agent send the fixed tool
    call to MCP Reflex.  Later cognitive agents can reuse the run lifecycle
    without inheriting a privilege to invent MCP arguments.
    """

    def __init__(self) -> None:
        super().__init__()
        candidate = self.tree_node.get("config", {})
        self.config: dict[str, Any] = dict(candidate) if isinstance(candidate, Mapping) else {}
        self._enabled = self.config.get("enabled") is True
        self._workflows = self._load_workflows(self.config.get("workflows", {}))
        self._requesters = self._exact_id_set("authorized_requester_uids")
        self._approvers = self._exact_id_set("authorized_approver_uids")
        self._distinct_approver = self.config.get("require_distinct_approver") is not False

        self.init_encrypted_state(namespace="cognitive")
        self.init_cognitive_runs(
            max_active_runs=self._safe_positive("max_active_runs", 8, 64),
            max_retained_runs=self._safe_positive("max_retained_runs", 128, 1_024),
            default_turn_budget=self._safe_positive("default_turn_budget", 4, 128),
        )
        self.init_mcp_reflex_client(
            max_pending=self._safe_positive("max_pending_mcp_requests", 8, 128),
            request_timeout_sec=self._safe_positive("mcp_request_timeout_sec", 60, 600),
        )

    def pre_boot(self) -> None:
        if not self._enabled:
            self.log("[OPERATOR] Disabled by policy; no workflows can execute.", level="WARN")
        elif not self._workflows:
            self.log("[OPERATOR] No fixed workflows are configured; fail closed.", level="WARN")
        elif not self._requesters or not self._approvers:
            self.log("[OPERATOR] Requester/approver identities are not configured; fail closed.", level="WARN")
        else:
            self.log(
                "[OPERATOR] Approval-gated workflows ready: "
                + ",".join(sorted(self._workflows))
            )

    def worker(self, config: dict | None = None, identity=None) -> None:
        self.expire_mcp_requests()
        interruptible_sleep(self, 2)

    def cmd_operator_request(
        self, content: Any, _packet: Any, identity: IdentityObject | None = None
    ) -> None:
        """Create an approval-gated run for one fixed workflow."""
        sender_uid = self._verified_sender(identity)
        if sender_uid is None or sender_uid not in self._requesters:
            self._audit("DENY", sender_uid, None, "request", "unauthorized requester", "WARN")
            return
        if not self._ready_for_workflow():
            self._audit("DENY", sender_uid, None, "request", "operator is not ready", "WARN")
            return
        if not isinstance(content, Mapping):
            self._audit("DENY", sender_uid, None, "request", "content must be a mapping", "WARN")
            return
        try:
            workflow_id = self._required_text(content, "workflow_id", 128)
            workflow = self._workflows.get(workflow_id)
            if workflow is None:
                raise CognitiveRunError("workflow is not allowed")
            run_id = content.get("run_id")
            if run_id is None:
                run_id = f"run-{secrets.token_hex(16)}"
            if not isinstance(run_id, str):
                raise CognitiveRunError("run_id is invalid")
            run = self.create_cognitive_run(
                run_id,
                workflow_id=workflow_id,
                requested_by=sender_uid,
                server_id=workflow["server_id"],
                tool_name=workflow["tool_name"],
                arguments=workflow["arguments"],
                turn_budget=workflow["turn_budget"],
            )
            self._audit("REQUESTED", sender_uid, run["run_id"], workflow_id, "awaiting approval")
        except CognitiveRunError as exc:
            self._audit("DENY", sender_uid, self._request_id(content), "request", str(exc), "WARN")

    def cmd_operator_approve(
        self, content: Any, _packet: Any, identity: IdentityObject | None = None
    ) -> None:
        """Approve a run and send its policy-owned MCP request."""
        sender_uid = self._verified_sender(identity)
        run_id = self._request_id(content)
        if sender_uid is None or sender_uid not in self._approvers:
            self._audit("DENY", sender_uid, run_id, "approve", "unauthorized approver", "WARN")
            return
        if not isinstance(content, Mapping) or run_id is None:
            self._audit("DENY", sender_uid, run_id, "approve", "run_id is required", "WARN")
            return
        try:
            run = self.get_cognitive_run(run_id)
            if run is None:
                raise CognitiveRunError("unknown cognitive run")
            if self._distinct_approver and run.get("requested_by") == sender_uid:
                raise CognitiveRunError("requester cannot approve its own run")
            approved = self.approve_cognitive_run(run_id, sender_uid)
            request_id = f"operator-{run_id}"
            self.mark_cognitive_dispatching(run_id, request_id)
            mcp = run.get("mcp", {})
            self.request_mcp_tool_call(
                mcp["server_id"],
                mcp["tool_name"],
                mcp["arguments"],
                request_id=request_id,
                context={"run_id": run_id, "workflow_id": approved["workflow_id"]},
            )
            self._audit("DISPATCH", sender_uid, run_id, approved["workflow_id"], "MCP request sent")
        except (CognitiveRunError, McpReflexClientError, KeyError) as exc:
            if run_id is not None:
                self._mark_dispatch_failure(run_id, str(exc))
            self._audit("DENY", sender_uid, run_id, "approve", str(exc), "WARN")

    def cmd_operator_deny(
        self, content: Any, _packet: Any, identity: IdentityObject | None = None
    ) -> None:
        """Deny a pending run before it can leave the cognitive agent."""
        sender_uid = self._verified_sender(identity)
        run_id = self._request_id(content)
        if sender_uid is None or sender_uid not in self._approvers:
            self._audit("DENY", sender_uid, run_id, "deny", "unauthorized approver", "WARN")
            return
        if not isinstance(content, Mapping) or run_id is None:
            self._audit("DENY", sender_uid, run_id, "deny", "run_id is required", "WARN")
            return
        try:
            self.deny_cognitive_run(run_id, sender_uid)
            self._audit("DENIED", sender_uid, run_id, "deny", "operator denied request")
        except CognitiveRunError as exc:
            self._audit("DENY", sender_uid, run_id, "deny", str(exc), "WARN")

    def on_mcp_result(self, content: dict[str, Any], pending: Mapping[str, Any]) -> None:
        """Persist the verified airlock callback without logging its payload."""
        context = pending.get("context")
        run_id = context.get("run_id") if isinstance(context, Mapping) else None
        if not isinstance(run_id, str):
            self._audit("DROP", None, None, "callback", "run context missing", "WARN")
            return
        status = content.get("status")
        try:
            if status == "ok":
                completed = self.complete_cognitive_run(
                    run_id, state="completed", result=content.get("result")
                )
                self._audit("COMPLETE", None, run_id, completed["workflow_id"], "verified MCP result")
            elif status == "denied":
                completed = self.complete_cognitive_run(
                    run_id, state="denied", error=str(content.get("error", "MCP request denied"))
                )
                self._audit("MCP-DENIED", None, run_id, completed["workflow_id"], "airlock denied", "WARN")
            else:
                completed = self.complete_cognitive_run(
                    run_id, state="failed", error=str(content.get("error", "MCP request failed"))
                )
                self._audit("MCP-FAILED", None, run_id, completed["workflow_id"], "airlock error", "WARN")
        except CognitiveRunError as exc:
            self._audit("CALLBACK-FAIL", None, run_id, "callback", str(exc), "ERROR")

    def on_mcp_timeout(self, _request_id: str, pending: Mapping[str, Any]) -> None:
        context = pending.get("context")
        run_id = context.get("run_id") if isinstance(context, Mapping) else None
        if not isinstance(run_id, str):
            return
        try:
            completed = self.complete_cognitive_run(
                run_id, state="timed_out", error="MCP callback timed out"
            )
            self._audit("TIMEOUT", None, run_id, completed["workflow_id"], "MCP callback timed out", "WARN")
        except CognitiveRunError as exc:
            self._audit("CALLBACK-FAIL", None, run_id, "timeout", str(exc), "ERROR")

    def _ready_for_workflow(self) -> bool:
        return self._enabled and bool(self._workflows) and bool(self._requesters) and bool(self._approvers)

    @staticmethod
    def _verified_sender(identity: IdentityObject | None) -> str | None:
        if not isinstance(identity, IdentityObject) or not identity.has_verified_identity():
            return None
        uid = identity.get_sender_uid()
        return uid if isinstance(uid, str) and uid else None

    def _exact_id_set(self, key: str) -> frozenset[str]:
        values = self.config.get(key, [])
        if not isinstance(values, list):
            return frozenset()
        valid = {
            value.strip()
            for value in values
            if isinstance(value, str)
            and value.strip()
            and len(value.strip()) <= 128
            and all(control not in value for control in ("\x00", "\r", "\n"))
        }
        return frozenset(valid)

    def _load_workflows(self, value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, Mapping):
            return {}
        workflows: dict[str, dict[str, Any]] = {}
        for workflow_id, raw in value.items():
            try:
                self._validate_workflow_id(workflow_id)
                if not isinstance(raw, Mapping):
                    raise CognitiveRunError("workflow must be a mapping")
                server_id = self._required_text(raw, "server_id", 128)
                tool_name = self._required_text(raw, "tool_name", 128)
                arguments = raw.get("arguments", {})
                if not isinstance(arguments, Mapping):
                    raise CognitiveRunError("workflow arguments must be a mapping")
                if raw.get("requires_approval") is not True:
                    raise CognitiveRunError("workflow must require approval")
                turn_budget = raw.get("turn_budget", self.config.get("default_turn_budget", 4))
                if isinstance(turn_budget, bool) or not isinstance(turn_budget, int) or not 1 <= turn_budget <= 128:
                    raise CognitiveRunError("workflow turn_budget is invalid")
                # Ensures values are serializable before an operator can queue work.
                self._json_bytes(arguments, "workflow arguments")
                workflows[workflow_id] = {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "arguments": dict(arguments),
                    "turn_budget": turn_budget,
                }
            except CognitiveRunError:
                self.log(f"[OPERATOR] Ignoring unsafe workflow {str(workflow_id)[:64]!r}", level="WARN")
        return workflows

    def _safe_positive(self, key: str, default: int, maximum: int) -> int:
        value = self.config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            return default
        return value

    @staticmethod
    def _required_text(content: Mapping[str, Any], field: str, maximum: int) -> str:
        value = content.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > maximum
            or any(control in value for control in ("\x00", "\r", "\n"))
        ):
            raise CognitiveRunError(f"{field} is invalid")
        return value.strip()

    @staticmethod
    def _request_id(content: Any) -> str | None:
        if not isinstance(content, Mapping):
            return None
        value = content.get("run_id")
        return value if isinstance(value, str) else None

    def _mark_dispatch_failure(self, run_id: str, reason: str) -> None:
        try:
            run = self.get_cognitive_run(run_id)
            if run is not None and run.get("state") == "dispatching":
                self.complete_cognitive_run(run_id, state="failed", error=reason)
        except CognitiveRunError:
            pass

    def _audit(
        self,
        event: str,
        sender_uid: str | None,
        run_id: str | None,
        operation: str,
        detail: str,
        level: str = "INFO",
    ) -> None:
        sender = sender_uid if isinstance(sender_uid, str) else "agent"
        run = run_id[:16] if isinstance(run_id, str) else "unknown"
        safe_detail = str(detail).replace("\r", " ").replace("\n", " ")[:192]
        self.log(
            f"[OPERATOR][{event}] sender={sender[:128]} run={run} "
            f"operation={operation[:128]} {safe_detail}".rstrip(),
            level=level,
        )


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
