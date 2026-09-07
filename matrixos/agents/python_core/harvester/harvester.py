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
)
from harvester.ssh_transport import run_matrixd_list


class Agent(BootAgent):
    """Observation-only matrixd watcher for one assigned universe."""

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
        self.targets = self._load_targets(self.config.get("targets", []))
        self._states = {target["id"]: initial_state() for target in self.targets}
        self._emit_beacon = self.check_for_thread_poke(
            "worker", timeout=self.interval * 6, emit_to_file_interval=10
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
            self.log(
                f"[HARVESTER] Watching target={self.targets[0]['id']} via "
                f"{self.mode} matrixd; observation-only policy active."
            )

    def worker(self, config: dict | None = None, identity=None) -> None:
        if self._ready():
            self._run_cycle()
        self._emit_beacon()
        interruptible_sleep(self, self.interval)

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
        except Exception as exc:
            universes = {}
            collection_error = type(exc).__name__[:64]
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
                self._emit_alert(target, event, status, observed_at)

    def _matrixd_list(self) -> str:
        if self.mode == "ssh":
            return run_matrixd_list(dict(self.config["ssh"]), self.timeout)

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

    def _emit_alert(self, target, event, status, observed_at) -> None:
        endpoints = self.get_nodes_by_role(self.alert_role)
        if not endpoints:
            self.log(
                f"[HARVESTER][ALERT] No endpoint for role={self.alert_role}",
                level="WARN",
            )
            return
        alert = self.get_delivery_packet("notify.alert.general", new=True)
        alert.set_data(
            {
                "msg": (
                    f"Harvester {event}: {target['id']} "
                    f"({status}; universe={target['universe']})"
                ),
                "level": "success" if event == "RECOVERY" else "critical",
                "origin": self.command_line_args.get(
                    "universal_id", "harvester"
                ),
                "cause": f"Harvester {event}",
                "observed_at": observed_at,
            }
        )
        packet = self.get_delivery_packet("standard.command.packet", new=True)
        packet.set_packet(alert, "content")
        for endpoint in endpoints:
            packet.set_payload_item("handler", endpoint.get_handler())
            self.pass_packet(packet, endpoint.get_universal_id())
        self.log(f"[HARVESTER][ALERT] event={event} target={target['id']}")

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
