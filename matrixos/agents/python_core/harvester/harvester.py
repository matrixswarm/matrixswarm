"""Observe local or SSH-reachable swarms through ``matrixd list --json``."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Mapping
from typing import Any

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.python_core.boot_agent import BootAgent
from core.python_core.utils.swarm_sleep import interruptible_sleep
from harvester.policy import (
    HarvesterPolicyError,
    evaluate_observation,
    initial_state,
    normalize_target,
    observation_for_target,
    parse_matrixd_snapshot,
    record_recovery_attempt,
    recovery_due,
)
from harvester.ssh_transport import run_matrixd_boot
from harvester.ssh_check import SSHCheckCancelled, SSHCheckError, SSHCheckRunner


class Agent(BootAgent):
    """Observe one assigned universe and apply only its granted authority."""

    def __init__(self) -> None:
        super().__init__()
        candidate = self.tree_node.get("config", {})
        self.config: dict[str, Any] = (
            dict(candidate) if isinstance(candidate, Mapping) else {}
        )
        self.enabled = self.config.get("enabled") is True
        configured_mode = self.config.get("mode")
        self.mode = configured_mode if configured_mode in {"local", "ssh"} else "invalid"
        self.interval = self._bounded_config_int(
            "check_interval_sec", 30, 5, 3_600
        )
        self.timeout = self._bounded_config_int("matrixd_timeout_sec", 60, 2, 300)
        self.alert_role = self._role("alert_to_role", "hive.alert")
        self.automatic_recovery_requested = (
            self.config.get("automatic_recovery_enabled") is True
        )
        # Resurrection remains deliberately dormant until its authority and
        # sealed-stream handoff receive a separate operator approval cycle.
        self.automatic_recovery_enabled = False
        self.targets = self._load_targets(self.config.get("targets", []))
        self._states = {target["id"]: initial_state() for target in self.targets}
        self._pending_alerts: dict[str, dict[str, Any]] = {}
        self._alert_retry_log_at: dict[str, float] = {}
        self._first_checks_logged: set[str] = set()
        self._ssh_checker = SSHCheckRunner()
        self._emit_beacon = self.check_for_thread_poke(
            "worker", timeout=max(60, self.interval * 6, self.timeout + self.interval + 30),
            emit_to_file_interval=10,
        )

    def pre_boot(self) -> None:
        if not self.enabled:
            self.log(
                "[HARVESTER] Disabled by policy; no matrixd checks will run.",
                level="WARN",
            )
        elif self.mode == "invalid":
            self.log(
                "[HARVESTER] Mode must be local or ssh; fail closed.",
                level="ERROR",
            )
        elif self.mode == "ssh" and not isinstance(
            self.config.get("ssh"), Mapping
        ):
            self.log(
                "[HARVESTER] SSH mode has no Phoenix-provisioned profile; fail closed.",
                level="ERROR",
            )
        elif not self.targets:
            self.log(
                "[HARVESTER] No valid universes configured; fail closed.",
                level="WARN",
            )
        else:
            if self.automatic_recovery_requested:
                self.log(
                    "[HARVESTER] Automatic recovery was requested but is "
                    "disabled by the current observation-only release.",
                    level="WARN",
                )
            self.log(
                f"[HARVESTER] Watching target={self.targets[0]['id']} via "
                f"{self.mode} matrixd; automatic_recovery="
                f"{self.automatic_recovery_enabled}; check_timeout={self.timeout}s."
            )

    def worker(self, config: dict | None = None, identity=None) -> None:
        self._emit_beacon()
        if self._ready():
            self._run_cycle()
        self._emit_beacon()
        interruptible_sleep(self, self.interval)

    def worker_post(self):
        self._ssh_checker.close()

    def shutdown_now(self, reason="normal"):
        try:
            self._ssh_checker.close()
        except SSHCheckError as exc:
            self.log(f"[HARVESTER][CHECK] Shutdown: {exc.code}", level="ERROR")
        finally:
            super().shutdown_now(reason)

    def _ready(self) -> bool:
        return (
            self.enabled
            and self.mode in {"local", "ssh"}
            and bool(self.targets)
            and (
                self.mode != "ssh"
                or isinstance(self.config.get("ssh"), Mapping)
            )
        )

    def _run_cycle(self) -> None:
        observed_at = time.time()
        try:
            universes = parse_matrixd_snapshot(self._matrixd_list())
            collection_error = None
        except SSHCheckCancelled:
            return
        except Exception as exc:
            universes = {}
            collection_error = (
                exc.code if isinstance(exc, SSHCheckError)
                else type(exc).__name__[:64]
            )
            self.log(
                f"[HARVESTER][CHECK] mode={self.mode} matrixd list failed: "
                f"{collection_error}",
                level="WARN",
            )

        for target in self.targets:
            success, status = (
                (False, collection_error)
                if collection_error
                else observation_for_target(target, universes)
            )
            target_id = target["id"]
            if target_id not in self._first_checks_logged:
                self._first_checks_logged.add(target_id)
                self.log(
                    f"[HARVESTER][CHECK] Initial observation target={target_id} "
                    f"universe={target['universe']} mode={self.mode} "
                    f"result={'healthy' if success else 'unhealthy'} "
                    f"status={status}; checks continue every {self.interval}s.",
                    level="INFO" if success else "WARN",
                )
            try:
                state, event = evaluate_observation(
                    self._states[target_id],
                    success=success,
                    observed_at=observed_at,
                    target=target,
                )
                self._states[target_id] = state
            except HarvesterPolicyError as exc:
                self.log(
                    f"[HARVESTER][POLICY] target={target_id} {exc}",
                    level="ERROR",
                )
                continue
            if event is not None:
                self._queue_alert(target, event)
            self._retry_alert(target, success, status, observed_at)
            if recovery_due(
                state,
                target,
                globally_enabled=self.automatic_recovery_enabled,
                collection_available=collection_error is None,
                observed_at=observed_at,
            ):
                self._states[target_id] = record_recovery_attempt(
                    state, observed_at=observed_at
                )
                self._attempt_recovery(target)

    def _matrixd_list(self) -> str:
        if self.mode == "ssh":
            return self._ssh_checker.run(
                dict(self.config["ssh"]), self.timeout,
                pulse=self._emit_beacon, cancelled=lambda: not self.running,
            )

        command = [
            sys.executable,
            "/matrix/scripts/matrixd",
            "list",
            "--json",
        ]
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout,
            check=False,
            cwd="/matrix",
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"local matrixd list failed with status {completed.returncode}"
            )
        if completed.stderr.strip():
            raise RuntimeError("local matrixd list wrote to stderr")
        if len(completed.stdout.encode("utf-8")) > 1_048_576:
            raise RuntimeError("local matrixd list output exceeded limit")
        return completed.stdout

    def _queue_alert(self, target, event) -> None:
        target_id = target["id"]
        pending = self._pending_alerts.get(target_id)
        # One current notification per target, not an unbounded outage history.
        # Reminders must not reset partial delivery and spam successful relays.
        if event == "DOWN_REMINDER" and pending is not None:
            if pending["event"] in {"DOWN", "DOWN_REMINDER"}:
                return
        self._pending_alerts[target_id] = {"event": event, "delivered_to": set()}

    def _retry_alert(self, target, success, status, observed_at) -> None:
        target_id = target["id"]
        pending = self._pending_alerts.get(target_id)
        if pending is None:
            return
        # Never send a queued healthy message after a failed check, nor a down
        # notice during recovery debounce. The next transition supersedes it.
        healthy_event = pending["event"] in {"HEALTHY", "RECOVERY"}
        if healthy_event != success:
            return
        try:
            dispatched = self._emit_alert(
                target, pending["event"], status, observed_at,
                delivered_to=pending["delivered_to"],
            )
        except Exception as exc:
            self._warn_alert_pending(target_id, type(exc).__name__[:64])
            return
        if dispatched:
            del self._pending_alerts[target_id]
            self._alert_retry_log_at.pop(target_id, None)
            # Cooldown starts on dispatch, not when discovery was unavailable.
            if not healthy_event:
                self._states[target_id]["last_alert_at"] = observed_at

    def _warn_alert_pending(self, target_id, reason) -> None:
        now = time.monotonic()
        previous = self._alert_retry_log_at.get(target_id)
        if previous is None or now - previous >= 60:
            self._alert_retry_log_at[target_id] = now
            self.log(
                f"[HARVESTER][ALERT] Pending target={target_id}: {reason}; "
                "will retry on the next check. Health monitoring continues.",
                level="WARN",
            )

    def _emit_alert(
        self, target, event, status, observed_at, *, delivered_to
    ) -> bool:
        endpoints = self.get_nodes_by_role(self.alert_role)
        if not endpoints:
            self._warn_alert_pending(
                target["id"], f"No endpoint for role={self.alert_role}"
            )
            return False
        recipients = {
            (endpoint.get_universal_id(), endpoint.get_handler())
            for endpoint in endpoints
        }
        # Bound retry bookkeeping to the current catalog as services change.
        delivered_to.intersection_update(recipients)
        alert = self.get_delivery_packet("notify.alert.general", new=True)
        healthy_suffix = (
            "; monitoring established. Further notices will be sent only "
            "if health changes"
            if event == "HEALTHY"
            else ""
        )
        alert.set_data(
            {
                "msg": (
                    f"Harvester {event}: {target['id']} "
                    f"({status}; universe={target['universe']})"
                    f"{healthy_suffix}"
                ),
                "level": (
                    "success"
                    if event in {"HEALTHY", "RECOVERY"}
                    else "critical"
                ),
                "origin": self.command_line_args.get(
                    "universal_id", "harvester"
                ),
                "universal_id": self.command_line_args.get(
                    "universal_id", "harvester"
                ),
                "cause": f"Harvester {event}",
            }
        )
        alert.set_payload_item("observed_at", observed_at)
        for uid, handler in sorted(recipients - delivered_to):
            try:
                packet = self.get_delivery_packet("standard.command.packet", new=True)
                packet.set_data({"handler": handler})
                # The alert is already populated. Default nested auto-fill
                # would reload it from the command's empty content and invalidate
                # the shared alert, leaving later recipients without a message.
                packet.set_auto_fill_sub_packet(False)
                packet.set_packet(alert, "content")
                if self.pass_packet(packet, uid):
                    delivered_to.add((uid, handler))
            except Exception as exc:
                self._warn_alert_pending(target["id"], type(exc).__name__[:64])
        if delivered_to != recipients:
            self._warn_alert_pending(target["id"], "Packet dispatch incomplete")
            return False
        self.log(
            f"[HARVESTER][ALERT] Dispatched event={event} target={target['id']}",
            level=(
                "INFO"
                if event in {"HEALTHY", "RECOVERY"}
                else "CRITICAL"
            ),
        )
        return True

    def _attempt_recovery(self, target) -> None:
        try:
            run_matrixd_boot(dict(self.config["ssh"]), target, self.timeout)
            self.log(
                f"[HARVESTER][RECOVERY] Boot launched for target="
                f"{target['id']}",
                level="WARN",
            )
        except Exception as exc:
            self.log(
                f"[HARVESTER][RECOVERY] Boot failed for target="
                f"{target['id']} error={type(exc).__name__[:64]}",
                level="ERROR",
            )

    def _load_targets(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or len(value) > 1:
            self.log(
                "[HARVESTER] Phase-1 policy requires zero or one target; "
                "ignoring the target list.",
                level="WARN",
            )
            return []
        targets, seen = [], set()
        for offset, raw in enumerate(value):
            try:
                target = normalize_target(raw)
                if target["id"] in seen:
                    raise HarvesterPolicyError("duplicate target id")
                seen.add(target["id"])
                targets.append(target)
            except HarvesterPolicyError as exc:
                self.log(
                    f"[HARVESTER] Ignoring unsafe target #{offset + 1}: {exc}",
                    level="WARN",
                )
        return targets

    def _bounded_config_int(
        self, key: str, default: int, minimum: int, maximum: int
    ) -> int:
        value = self.config.get(key, default)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and minimum <= value <= maximum
        ):
            return value
        return default

    def _role(self, key: str, default: str) -> str:
        value = self.config.get(key, default)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > 128
            or any(character in value for character in ("\x00", "\r", "\n"))
        ):
            return default
        return value.strip()


if __name__ == "__main__":
    Agent().boot()
