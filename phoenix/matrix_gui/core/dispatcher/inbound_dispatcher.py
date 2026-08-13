# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from matrix_gui.core.class_lib.packet_delivery.utility.encryption.utility.unwrap_secure_packet import (
    unwrap_secure_packet,
)
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class InboundDispatcher:
    def __init__(self, bus, session_id=None):
        self.bus = bus
        self._session_id = session_id
        self._resolved_channel = None
        bus.on("inbound.message", self._handle_inbound)

    def _get_ctx(self):
        try:
            return get_sessions().get(self._session_id)
        except Exception as error:
            emit_gui_exception_log("InboundDispatcher._get_ctx", error)
            return None

    def get_inbound_connection(self):
        if not isinstance(self._resolved_channel, dict):
            return None
        connection = self._resolved_channel.get("connection") or {}
        return self._resolved_channel if connection.get("channel") == "payload.reception" else None

    def set_inbound_connector(self, agent: dict):
        """Bind the live payload.reception channel selected by the operator."""
        ctx = self._get_ctx()
        if ctx is None or not isinstance(agent, dict):
            return

        connection = agent.get("connection") or {}
        if (connection.get("channel") or "").strip().lower() != "payload.reception":
            return

        selected_uid = agent.get("universal_id")
        selected_proto = (connection.get("proto") or "").strip().lower()
        resolved_channel = None

        for live_agent in (getattr(ctx, "channels", {}) or {}).values():
            if live_agent.get("universal_id") == selected_uid:
                resolved_channel = live_agent
                break

        if not resolved_channel and selected_proto:
            for live_agent in (getattr(ctx, "channels", {}) or {}).values():
                live_connection = live_agent.get("connection") or {}
                if (
                    (live_connection.get("channel") or "").strip().lower() == "payload.reception"
                    and (live_connection.get("proto") or "").strip().lower() == selected_proto
                ):
                    resolved_channel = live_agent
                    break

        if not resolved_channel:
            print(f"[INBOUND DISPATCHER] ❌ No active connector found for inbound agent '{selected_uid}'")
            return

        self._resolved_channel = resolved_channel
        print(f"[INBOUND DISPATCHER] ✅ Bound inbound connector → {resolved_channel.get('universal_id')}")

    @staticmethod
    def _extract_signed_wrapper(payload):
        """Return ``(signed_wrapper, routing_handler)`` for either wire form.

        IMAP has already authenticated/decrypted its transport envelope and
        forwards ``{matrix_packet, session_id, ts}``.  The Matrix packet holds
        the callback wrapper in its ``content`` field.  Direct connector tests
        may instead forward that signed wrapper by itself.
        """
        if not isinstance(payload, dict):
            return None, None

        matrix_packet = payload.get("matrix_packet", payload)
        if not isinstance(matrix_packet, dict):
            return None, None

        candidate = matrix_packet.get("content")
        if isinstance(candidate, dict) and "serial" in candidate and "sig" in candidate:
            return candidate, matrix_packet.get("handler")

        if "serial" in matrix_packet and "sig" in matrix_packet:
            return matrix_packet, matrix_packet.get("handler")

        return None, None

    @staticmethod
    def _resolve_signing(deployment, serial):
        """Resolve the sender's signing public key and recipient private key."""
        if not isinstance(deployment, dict):
            return None

        agents = deployment.get("agents") or []
        certs = deployment.get("certs") or {}
        if not isinstance(agents, list) or not isinstance(certs, dict):
            return None

        for agent in agents:
            if isinstance(agent, dict) and agent.get("serial") == serial:
                universal_id = agent.get("universal_id")
                cert_block = certs.get(universal_id) or {}
                signing = cert_block.get("signing") or {}
                if not isinstance(signing, dict):
                    return None

                public_key = signing.get("pubkey")
                private_key = signing.get("remote_privkey")
                if not public_key or not private_key:
                    return None

                return public_key, private_key
        return None

    def _handle_inbound(self, session_id, channel, source, payload, ts=None, **_):
        """Verify one agent callback, then emit only its authenticated content.

        Expected cryptographic failures remain inside ``unwrap_secure_packet``.
        This method deliberately has no broad ``try/except`` that could hide a
        programming fault or accidentally continue with an unverified packet.
        """
        if self._resolved_channel:
            allowed_uid = self._resolved_channel.get("universal_id")
            if channel != allowed_uid:
                print(f"[INBOUND] ⛔ Ignoring packet from {channel}; active inbound is {allowed_uid}")
                return

        if not isinstance(payload, dict):
            print("[INBOUND] ❌ Invalid payload type")
            return

        signed_wrapper, outer_handler = self._extract_signed_wrapper(payload)
        if signed_wrapper is None:
            print("[INBOUND] ❌ Missing signed callback wrapper")
            return

        serial = signed_wrapper.get("serial")
        if not isinstance(serial, str):
            print("[INBOUND] ❌ Serial must be a string")
            return

        serial = serial.strip()
        if len(serial) != 64:
            print("[INBOUND] ❌ Serial must be exactly 64 characters")
            return

        ctx = get_sessions().get(session_id)
        deployment = ctx.group.get("deployment", {}) if ctx else {}
        keys = self._resolve_signing(deployment, serial)
        if keys is None:
            print(f"[INBOUND] ❌ No certificate found for serial {serial}")
            return

        signer_pubkey_pem, recipient_privkey_pem = keys

        # The helper owns signature verification, authenticated timestamp and
        # replay checks, and AES decryption.  It returns None on every normal
        # rejection, leaving no crypto exception path in this dispatcher.
        directive = unwrap_secure_packet(
            {"content": signed_wrapper},
            remote_pubkey=signer_pubkey_pem,
            local_privkey=recipient_privkey_pem,
            logger=print,
        )

        if not isinstance(directive, dict):
            return

        handler = directive.get("handler")

        if outer_handler and outer_handler != handler:
            print("[INBOUND] ❌ Outer/inner handler mismatch")
            return

        if not isinstance(handler, str) or not handler.strip():
            print("[INBOUND] ❌ Missing verified handler")
            return

        packet_timestamp = signed_wrapper["timestamp"]
        verified_payload = {
            "handler": handler,
            "content": directive.get("content", directive),
            "timestamp": packet_timestamp,
            "ts": packet_timestamp,
        }
        self.bus.emit(
            f"inbound.verified.{handler}",
            session_id=session_id,
            channel=channel,
            source=source,
            payload=verified_payload,
            ts=packet_timestamp,
        )
        print(f"[INBOUND] ✅ emitted inbound.verified.{handler}")