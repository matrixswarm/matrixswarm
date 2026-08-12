import time


class ReflexAlertMixin:
    """Send reflex alerts through the normal swarm packet-delivery lane."""

    def alert_operator(self, qid=None, message=None, level="critical", cause="[PARSE ERROR]", roles=None):
        message = message or "🚨 Reflex termination (exit_code = -1)"

        try:
            endpoints = self._resolve_reflex_alert_endpoints(roles)
            if not endpoints:
                self._log_reflex(f"[REFLEX][ALERT] No agents found for roles: {self._reflex_alert_roles(roles)}. Alert not dispatched.")
                return False

            payload = self._build_reflex_alert_payload(
                message=message,
                level=level,
                cause=cause,
                qid=qid,
            )

            dispatched = self._dispatch_reflex_alert(endpoints, payload)
            if dispatched:
                self._log_reflex(
                    f"[REFLEX] Alert dispatched to {dispatched} endpoint(s) "
                    f"from {payload.get('origin', 'unknown')}.",
                    level="WARN",
                    block="DROP_ALERT",
                )
            return bool(dispatched)

        except Exception as e:
            self._log_reflex("[REFLEX][ERROR] Failed to dispatch reflex alert.", error=e, level="ERROR", block="main_try")
            return False

    def drop_reflex_alert(self, message, agent_dir=None, level="critical", cause="reflex-trigger", handler=None):
        """
        Legacy name retained for existing agents.

        Old behavior wrote directly to another agent's incoming directory. The
        mixin now sends the same alert content through BootAgent's packet API,
        matching the send_simple_alert pattern used by watchdog agents.
        """
        try:
            payload = self._build_reflex_alert_payload(
                message=message,
                level=level,
                cause=cause,
            )

            if agent_dir:
                endpoint = {
                    "universal_id": agent_dir,
                    "handler": handler or "cmd_send_alert_msg",
                }
                return bool(self._dispatch_reflex_alert([endpoint], payload))

            return self.alert_operator(message=message, level=level, cause=cause)

        except Exception as e:
            self._log_reflex("[REFLEX][ERROR] Failed to drop reflex alert.", error=e, level="ERROR", block="main_try")
            return False

    def _reflex_alert_roles(self, roles=None):
        if roles is None:
            cfg = {}
            tree_node = getattr(self, "tree_node", {})
            if isinstance(tree_node, dict):
                cfg = tree_node.get("config", {}) or {}

            roles = (
                getattr(self, "alert_roles", None)
                or getattr(self, "alert_role", None)
                or cfg.get("alert_roles")
                or cfg.get("alert_to_role")
                or ["comm"]
            )

        if isinstance(roles, str):
            return [roles]
        return list(roles or [])

    def _resolve_reflex_alert_endpoints(self, roles=None):
        endpoints = []
        seen = set()

        for role in self._reflex_alert_roles(roles):
            found = self.get_nodes_by_role(role) or []
            for endpoint in found:
                universal_id = self._endpoint_universal_id(endpoint)
                if not universal_id or universal_id in seen:
                    continue
                seen.add(universal_id)
                endpoints.append(endpoint)

        return endpoints

    def _build_reflex_alert_payload(self, message, level="critical", cause="reflex-trigger", qid=None):
        command_line_args = getattr(self, "command_line_args", {}) or {}
        origin = command_line_args.get("universal_id", "unknown")
        payload = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "universal_id": origin,
            "level": level,
            "msg": message,
            "formatted_msg": f"📣 Swarm Message\n{message}",
            "cause": cause,
            "origin": origin,
        }

        if qid is not None:
            payload["qid"] = qid

        return payload

    def _dispatch_reflex_alert(self, endpoints, payload):
        pk1 = self.get_delivery_packet("standard.command.packet")
        pk2 = self.get_delivery_packet("notify.alert.general")
        pk2.set_data(payload)
        pk1.set_packet(pk2, "content")

        dispatched = 0
        for endpoint in endpoints:
            universal_id = self._endpoint_universal_id(endpoint)
            handler = self._endpoint_handler(endpoint)

            if not universal_id:
                self._log_reflex(f"[REFLEX][ALERT] Skipping endpoint without universal_id: {endpoint}")
                continue
            if not handler:
                self._log_reflex(f"[REFLEX][ALERT] Skipping {universal_id}; endpoint has no handler.")
                continue

            pk1.set_payload_item("handler", handler)
            self.pass_packet(pk1, universal_id)
            dispatched += 1
            self._log_reflex(f"[REFLEX] Alert routed to {universal_id}")

        return dispatched

    def _endpoint_universal_id(self, endpoint):
        if hasattr(endpoint, "get_universal_id"):
            return endpoint.get_universal_id()
        if isinstance(endpoint, dict):
            return endpoint.get("universal_id") or endpoint.get("uid")
        return None

    def _endpoint_handler(self, endpoint):
        if hasattr(endpoint, "get_handler"):
            return endpoint.get_handler()
        if isinstance(endpoint, dict):
            return endpoint.get("handler") or self._default_reflex_handler()
        return self._default_reflex_handler()

    def _default_reflex_handler(self):
        cfg = {}
        tree_node = getattr(self, "tree_node", {})
        if isinstance(tree_node, dict):
            cfg = tree_node.get("config", {}) or {}
        return (
            getattr(self, "alert_handler", None)
            or getattr(self, "reflex_alert_handler", None)
            or cfg.get("alert_handler")
            or cfg.get("reflex_alert_handler")
            or "cmd_send_alert_msg"
        )

    def _log_reflex(self, message, error=None, level="INFO", block=None):
        try:
            if error is not None:
                self.log(message, error=error, level=level, block=block)
            elif block is not None and callable(getattr(self, "log_proto", None)):
                self.log_proto(message, level=level, block=block)
            else:
                self.log(message)
        except (AttributeError, TypeError):
            suffix = f" : {error}" if error is not None else ""
            self.log(f"{message}{suffix}")