"""One-shot signed probe for the MatrixSwarm MCP Reflex airlock."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.python_core.boot_agent import BootAgent
from core.python_core.mixin.mcp_reflex_client import (
    McpReflexClientError,
    McpReflexClientMixin,
)
from core.python_core.utils.swarm_sleep import interruptible_sleep


class Agent(McpReflexClientMixin, BootAgent):
    """Prove signed discovery, execution, denial, and callback routing."""

    def __init__(self) -> None:
        super().__init__()
        self.config = self.tree_node.get("config", {})
        self.init_mcp_reflex_client(max_pending=2, request_timeout_sec=60)
        self._probe_started = False
        self._probe_finished = False
        self._next_attempt = 0.0
        self._attempts = 0

    def worker(self, config: dict | None = None, identity=None) -> None:
        self.expire_mcp_requests()
        if (
            self._probe_finished
            or self._probe_started
            or self.config.get("run_on_boot") is not True
        ):
            interruptible_sleep(self, 2)
            return
        now = time.monotonic()
        if now < self._next_attempt:
            interruptible_sleep(self, 2)
            return
        self._attempts += 1
        try:
            self.request_mcp_tools(
                self._server_id(), context={"phase": "list_tools"}
            )
            self._probe_started = True
            self.log("[MCP-PROBE] Signed list_tools request sent.")
        except McpReflexClientError as exc:
            self._next_attempt = now + 5
            if self._attempts >= 12:
                self._fail(f"airlock endpoint unavailable: {exc}")
            else:
                self.log(f"[MCP-PROBE] Waiting for airlock endpoint: {exc}")
        interruptible_sleep(self, 2)

    def on_mcp_result(
        self, content: dict, pending: Mapping[str, object]
    ) -> None:
        context = pending.get("context")
        phase = context.get("phase") if isinstance(context, Mapping) else None
        try:
            if phase == "list_tools":
                if content.get("status") != "ok":
                    self._fail(f"list_tools failed: {content.get('error')}")
                    return
                tools = (content.get("result") or {}).get("tools", [])
                names = [
                    tool.get("name")
                    for tool in tools
                    if isinstance(tool, Mapping)
                ]
                if names != ["echo"]:
                    self._fail(f"discovery filter mismatch: {names}")
                    return
                self.log("[MCP-PROBE] ✅ Discovery exposed only echo.")
                self.request_mcp_tool_call(
                    self._server_id(),
                    "echo",
                    {
                        "message": self.config.get(
                            "message", "Airlock is tight"
                        )
                    },
                    context={"phase": "echo"},
                )
                return

            if phase == "echo":
                expected = self.config.get("message", "Airlock is tight")
                result = content.get("result") or {}
                structured = result.get("structuredContent", {})
                if (
                    content.get("status") != "ok"
                    or structured.get("message") != expected
                ):
                    self._fail("authorized echo result mismatch")
                    return
                self.log("[MCP-PROBE] ✅ Authorized echo crossed the airlock.")
                self.request_mcp_tool_call(
                    self._server_id(),
                    "hidden",
                    {},
                    context={"phase": "denied"},
                )
                return

            if phase == "denied":
                if content.get("status") != "denied":
                    self._fail("unauthorized tool was not denied")
                    return
                self._probe_finished = True
                self.log(
                    "[MCP-PROBE] ✅ PASS: signed caller, filtered discovery, "
                    "authorized execution, denied tool, and verified callback."
                )
        except McpReflexClientError as exc:
            self._fail(f"follow-up request failed: {exc}")

    def on_mcp_timeout(
        self, request_id: str, _pending: Mapping[str, object]
    ) -> None:
        self._fail(f"request timed out: {request_id}")

    def _server_id(self) -> str:
        value = self.config.get("server_id", "smoke")
        return value if isinstance(value, str) and value else "smoke"

    def _fail(self, reason: str) -> None:
        self._probe_finished = True
        self.log(f"[MCP-PROBE] ❌ FAIL: {reason}", level="ERROR")


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
