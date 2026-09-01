"""Durable, approval-gated run records for cognitive MatrixSwarm agents.

The mixin deliberately contains no LLM or MCP implementation.  It gives any
cognitive agent a small, encrypted state machine for a proposed action, the
operator decision that authorizes it, and the eventual external result.  An
agent such as ``operator_agent`` composes this with ``EncryptedStateMixin``
and an edge client such as ``McpReflexClientMixin``.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Mapping
from typing import Any


class CognitiveRunError(RuntimeError):
    """A cognitive run could not be created or transitioned safely."""


class CognitiveRunMixin:
    """Persist bounded, approval-gated cognitive work items.

    ``EncryptedStateMixin.init_encrypted_state()`` must be called before this
    mixin is initialized.  Run data is stored as encrypted checkpoints, while
    the index stores only bounded lifecycle metadata.  Tool arguments and
    results may be kept in encrypted checkpoints, but this mixin never writes
    either to logs.
    """

    _run_id_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    _workflow_id_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    _active_states = frozenset(
        {"awaiting_approval", "approved", "dispatching", "recovery_required"}
    )
    _terminal_states = frozenset(
        {"completed", "denied", "failed", "timed_out", "cancelled"}
    )

    def init_cognitive_runs(
        self,
        *,
        max_active_runs: int = 8,
        max_retained_runs: int = 128,
        default_turn_budget: int = 4,
    ) -> None:
        """Initialize a bounded run index after encrypted state is ready."""
        if not hasattr(self, "load_encrypted_state"):
            raise CognitiveRunError("encrypted state must be initialized first")
        for name, value, maximum in (
            ("max_active_runs", max_active_runs, 64),
            ("max_retained_runs", max_retained_runs, 1_024),
            ("default_turn_budget", default_turn_budget, 128),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise CognitiveRunError(f"{name} is outside its safe range")
        if max_retained_runs < max_active_runs:
            raise CognitiveRunError("max_retained_runs must cover active runs")
        self._cognitive_runs_lock = threading.RLock()
        self._cognitive_max_active_runs = max_active_runs
        self._cognitive_max_retained_runs = max_retained_runs
        self._cognitive_default_turn_budget = default_turn_budget
        index = self.load_encrypted_state("run_index", default={"runs": []})
        self._cognitive_index = self._validate_index(index)
        self._recover_interrupted_runs()

    def create_cognitive_run(
        self,
        run_id: str,
        *,
        workflow_id: str,
        requested_by: str,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        turn_budget: int | None = None,
    ) -> dict[str, Any]:
        """Create an encrypted run in ``awaiting_approval`` state.

        Callers must provide only a fixed, policy-owned workflow.  Arguments
        are encrypted in the checkpoint for recovery, never placed in the
        searchable index or emitted through the audit log.
        """
        self._validate_run_id(run_id)
        self._validate_workflow_id(workflow_id)
        requested_by = self._bounded_text(requested_by, "requested_by", 128)
        server_id = self._bounded_text(server_id, "server_id", 128)
        tool_name = self._bounded_text(tool_name, "tool_name", 128)
        if not isinstance(arguments, Mapping):
            raise CognitiveRunError("arguments must be a mapping")
        if len(self._json_bytes(arguments, "arguments")) > 131_072:
            raise CognitiveRunError("arguments exceed encrypted run limit")
        budget = self._cognitive_default_turn_budget if turn_budget is None else turn_budget
        if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 128:
            raise CognitiveRunError("turn_budget is outside its safe range")

        now = time.time()
        checkpoint = {
            "v": 1,
            "run_id": run_id,
            "workflow_id": workflow_id,
            "state": "awaiting_approval",
            "requested_by": requested_by,
            "created_at": now,
            "updated_at": now,
            "turn_budget": {"remaining": budget},
            "mcp": {
                "server_id": server_id,
                "tool_name": tool_name,
                "arguments": dict(arguments),
                "arguments_sha256": self._json_digest(arguments),
            },
            "events": [{"at": now, "event": "requested", "actor": requested_by}],
        }
        with self._cognitive_runs_lock:
            if any(entry["run_id"] == run_id for entry in self._cognitive_index["runs"]):
                raise CognitiveRunError("run_id already exists")
            active = sum(
                entry["state"] in self._active_states
                for entry in self._cognitive_index["runs"]
            )
            if active >= self._cognitive_max_active_runs:
                raise CognitiveRunError("cognitive active-run limit reached")
            self.save_encrypted_state("checkpoint", checkpoint, directory=f"runs/{run_id}")
            self._cognitive_index["runs"].append(self._index_entry(checkpoint))
            self._trim_index()
            self._save_cognitive_index()
        return self._public_run(checkpoint)

    def get_cognitive_run(self, run_id: str) -> dict[str, Any] | None:
        """Return the encrypted checkpoint for a known run, if retained."""
        self._validate_run_id(run_id)
        with self._cognitive_runs_lock:
            if not any(entry["run_id"] == run_id for entry in self._cognitive_index["runs"]):
                return None
            run = self.load_encrypted_state("checkpoint", directory=f"runs/{run_id}")
            if not isinstance(run, Mapping):
                raise CognitiveRunError("run checkpoint is invalid")
            return dict(run)

    def approve_cognitive_run(self, run_id: str, approved_by: str) -> dict[str, Any]:
        """Record an operator approval exactly once before dispatch."""
        return self._transition_run(
            run_id,
            expected={"awaiting_approval", "recovery_required"},
            state="approved",
            actor=self._bounded_text(approved_by, "approved_by", 128),
            event="approved",
            patch={"approval": {"approved_by": approved_by, "approved_at": time.time()}},
        )

    def deny_cognitive_run(
        self, run_id: str, denied_by: str, reason: str = "operator denied request"
    ) -> dict[str, Any]:
        """Terminate a pending action without ever contacting MCP."""
        return self._transition_run(
            run_id,
            expected={"awaiting_approval", "recovery_required", "approved"},
            state="denied",
            actor=self._bounded_text(denied_by, "denied_by", 128),
            event="denied",
            patch={"error": self._bounded_text(reason, "reason", 256)},
        )

    def mark_cognitive_dispatching(
        self, run_id: str, request_id: str
    ) -> dict[str, Any]:
        """Persist the exact outbound request ID before the external send."""
        return self._transition_run(
            run_id,
            expected={"approved"},
            state="dispatching",
            actor="agent",
            event="dispatching",
            patch={"mcp_request_id": self._bounded_text(request_id, "request_id", 128)},
        )

    def complete_cognitive_run(
        self,
        run_id: str,
        *,
        state: str,
        result: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Store a bounded external outcome and end the run."""
        if state not in {"completed", "denied", "failed", "timed_out"}:
            raise CognitiveRunError("invalid cognitive completion state")
        payload: dict[str, Any] = {}
        if result is not None:
            encoded = self._json_bytes(result, "result")
            if len(encoded) > 131_072:
                raise CognitiveRunError("result exceeds encrypted run limit")
            payload["result"] = result
            payload["result_sha256"] = hashlib.sha256(encoded).hexdigest()
        if error is not None:
            payload["error"] = self._bounded_text(error, "error", 256)
        return self._transition_run(
            run_id,
            expected={"dispatching", "approved"},
            state=state,
            actor="agent",
            event=state,
            patch=payload,
        )

    def cognitive_run_summary(self, run_id: str) -> dict[str, Any] | None:
        """Return non-sensitive lifecycle metadata suitable for a GUI/status log."""
        run = self.get_cognitive_run(run_id)
        return self._public_run(run) if run is not None else None

    def _transition_run(
        self,
        run_id: str,
        *,
        expected: set[str],
        state: str,
        actor: str,
        event: str,
        patch: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._validate_run_id(run_id)
        with self._cognitive_runs_lock:
            run = self.get_cognitive_run(run_id)
            if run is None:
                raise CognitiveRunError("unknown cognitive run")
            current = run.get("state")
            if current not in expected:
                raise CognitiveRunError(
                    f"cannot transition cognitive run from {current!r} to {state!r}"
                )
            now = time.time()
            run.update(dict(patch))
            run["state"] = state
            run["updated_at"] = now
            events = run.get("events")
            if not isinstance(events, list):
                events = []
            events.append({"at": now, "event": event, "actor": actor})
            run["events"] = events[-32:]
            self.save_encrypted_state("checkpoint", run, directory=f"runs/{run_id}")
            self._replace_index_entry(run)
            self._save_cognitive_index()
        return self._public_run(run)

    def _recover_interrupted_runs(self) -> None:
        """Never replay an external request automatically after a restart."""
        changed = False
        now = time.time()
        for entry in list(self._cognitive_index["runs"]):
            if entry["state"] != "dispatching":
                continue
            run_id = entry["run_id"]
            run = self.load_encrypted_state("checkpoint", directory=f"runs/{run_id}")
            if not isinstance(run, Mapping):
                raise CognitiveRunError("run checkpoint is invalid")
            recovered = dict(run)
            recovered["state"] = "recovery_required"
            recovered["updated_at"] = now
            events = recovered.get("events")
            if not isinstance(events, list):
                events = []
            events.append({"at": now, "event": "recovery_required", "actor": "agent"})
            recovered["events"] = events[-32:]
            self.save_encrypted_state("checkpoint", recovered, directory=f"runs/{run_id}")
            self._replace_index_entry(recovered)
            changed = True
        if changed:
            self._save_cognitive_index()

    def _validate_index(self, index: Any) -> dict[str, list[dict[str, Any]]]:
        if not isinstance(index, Mapping):
            raise CognitiveRunError("cognitive run index is invalid")
        runs = index.get("runs", [])
        if not isinstance(runs, list) or len(runs) > self._cognitive_max_retained_runs:
            raise CognitiveRunError("cognitive run index is invalid")
        validated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in runs:
            if not isinstance(entry, Mapping):
                raise CognitiveRunError("cognitive run index entry is invalid")
            run_id = entry.get("run_id")
            state = entry.get("state")
            workflow_id = entry.get("workflow_id")
            if not isinstance(run_id, str) or not self._run_id_re.fullmatch(run_id):
                raise CognitiveRunError("cognitive run index run_id is invalid")
            if run_id in seen or state not in self._active_states | self._terminal_states | {"approved"}:
                raise CognitiveRunError("cognitive run index contains an invalid state")
            if not isinstance(workflow_id, str) or not self._workflow_id_re.fullmatch(workflow_id):
                raise CognitiveRunError("cognitive run index workflow_id is invalid")
            seen.add(run_id)
            validated.append(dict(entry))
        return {"runs": validated}

    def _replace_index_entry(self, run: Mapping[str, Any]) -> None:
        entry = self._index_entry(run)
        for offset, current in enumerate(self._cognitive_index["runs"]):
            if current["run_id"] == entry["run_id"]:
                self._cognitive_index["runs"][offset] = entry
                return
        raise CognitiveRunError("run is absent from cognitive index")

    @staticmethod
    def _index_entry(run: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run["run_id"],
            "workflow_id": run["workflow_id"],
            "state": run["state"],
            "created_at": run["created_at"],
            "updated_at": run["updated_at"],
        }

    def _trim_index(self) -> None:
        runs = self._cognitive_index["runs"]
        if len(runs) <= self._cognitive_max_retained_runs:
            return
        terminal = [entry for entry in runs if entry["state"] in self._terminal_states]
        terminal.sort(key=lambda entry: entry["updated_at"])
        remove = len(runs) - self._cognitive_max_retained_runs
        removed = {entry["run_id"] for entry in terminal[:remove]}
        if len(removed) != remove:
            raise CognitiveRunError("cognitive run retention limit reached by active runs")
        self._cognitive_index["runs"] = [entry for entry in runs if entry["run_id"] not in removed]

    def _save_cognitive_index(self) -> None:
        self.save_encrypted_state("run_index", self._cognitive_index)

    @classmethod
    def _validate_run_id(cls, value: Any) -> None:
        if not isinstance(value, str) or not cls._run_id_re.fullmatch(value):
            raise CognitiveRunError("invalid cognitive run_id")

    @classmethod
    def _validate_workflow_id(cls, value: Any) -> None:
        if not isinstance(value, str) or not cls._workflow_id_re.fullmatch(value):
            raise CognitiveRunError("invalid cognitive workflow_id")

    @staticmethod
    def _bounded_text(value: Any, field: str, maximum: int) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > maximum
            or any(character in value for character in ("\x00", "\r", "\n"))
        ):
            raise CognitiveRunError(f"{field} is invalid")
        return value.strip()

    @classmethod
    def _json_digest(cls, value: Any) -> str:
        return hashlib.sha256(cls._json_bytes(value, "arguments")).hexdigest()

    @staticmethod
    def _json_bytes(value: Any, field: str) -> bytes:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CognitiveRunError(f"{field} must be JSON-compatible") from exc

    @staticmethod
    def _public_run(run: Mapping[str, Any]) -> dict[str, Any]:
        """Return summary fields only; never disclose tool arguments/results."""
        return {
            key: run[key]
            for key in ("run_id", "workflow_id", "state", "created_at", "updated_at")
            if key in run
        }
