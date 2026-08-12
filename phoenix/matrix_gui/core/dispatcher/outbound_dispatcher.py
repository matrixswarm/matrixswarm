# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely

class OutboundDispatcher:
    """
    Handles outbound message dispatch from the GUI to the MatrixSwarm.

    Listens on the event bus for outbound.message events, applies
    security wrapping (signing + encryption), and relays packets
    via a resolved connector (HTTPS/WSS/etc.).
    """

    def __init__(self, bus, session_id):
        """
        Initializes the dispatcher and binds outbound message listener.

        @param bus: EventBus instance for event binding.
        @param session_id: Session UUID for resolving context and connectors.
        @param _resolved_channel: Another word for an agent from a deployment
        """
        self._session_id = session_id
        self._outbound_connector = None
        self._resolved_channel = None
        bus.on("outbound.message", self._handle_outbound)

    def _get_ctx(self):
        """
        Internal helper to fetch the session context.

        @return: SessionContext or None if session not found.
        """
        try:
            return get_sessions().get(self._session_id)
        except Exception:
            return None

    def _get_launcher(self):
        """
        Internal helper to fetch the ConnectionLauncher from session context.

        @return: ConnectionLauncher object or None.
        """
        ctx = self._get_ctx()
        return ctx.group.get("connection_launcher") if ctx and isinstance(ctx.group, dict) else None

    def get_outbound_connection(self):
        """
        Retrieves the currently resolved outbound connection.

        @return: Dict with connector object and protocol, or None.
                 Example: { "connector": <HTTPSConnector>, "proto": "https" }
        """
        try:
            if not self._resolved_channel or not isinstance(self._resolved_channel, dict):
                print("OutboundDispatcher.get_outbound_connection no ctx or self._resolved_channel")
                return None

            agent = self._resolved_channel if self._resolved_channel.get("connection",{}).get("channel") == "outgoing.command" else None

            return agent

        except Exception as e:
            emit_gui_exception_log("OutboundDispatcher.get_outbound_connector", e)
            return None

    def set_outbound_connector(self, agent: dict):
        """
        Sets the outbound connector based on a selected agent.

        Looks up the agent's proto, then maps to the appropriate
        connector instance in the session's channel list.

        @param agent: Dictionary representing the selected agent config.
        """
        try:
            ctx = self._get_ctx()
            if ctx is None:
                return

            ch = agent.get("connection", {})
            proto = ch.get("proto") if ch.get("channel") == "outgoing.command" else None

            resolved_channel = None
            for uuid, agent in ctx.channels.items():
                if agent.get("connection", {}).get("proto", "").lower() == proto:
                    resolved_channel = agent
                    break

            if not resolved_channel:
                print(f"[DISPATCHER] ❌ No active connector for proto '{proto}' in session {self._session_id}")
                return

            self._resolved_channel = resolved_channel

        except Exception as e:
            emit_gui_exception_log("OutboundDispatcher.set_outbound_connector", e)
            return {}

    def _handle_outbound(self,
                         session_id,
                         channel,
                         packet: Packet,
                         security_sig=True,
                         security_encryption=True,
                         security_target_universal_id="matrix"):
        """
        Event handler for outbound.message

        Wraps the outgoing packet with signing/encryption, resolves
        the appropriate connector, and launches it via the session's
        ConnectionLauncher.

        @param session_id: ID of the session dispatching the packet.
        @param channel: Channel name (usually outgoing.command).
        @param packet: Packet object to be transmitted.
        @param security_sig: Whether to digitally sign the payload.
        @param security_encryption: Whether to encrypt the payload.
        @param security_target_universal_id: UID of the intended recipient.
        """
        try:
            ctx = self._get_ctx()
            if ctx is None:
                print("[OutboundDispatcher][_handle_outbound] ctx set None, aborting sending packet.")
                return

            dep = ctx.group.get("deployment", {}) if ctx else {}
            if not dep:
                print("[OutboundDispatcher][_handle_outbound] no deployment set, aborting sending packet.")
                return

            launcher = self._get_launcher()
            if not launcher:
                print("[OutboundDispatcher][_handle_outbound] no connection_launcher set, aborting sending packet.")
                return

            if not self._resolved_channel:
                print("[OutboundDispatcher][_handle_outbound] a resolved channel has not been set, aborting sending packet.")
                return

            # Matrix Signing & Encryption - Inner Packet
            original_data = packet.get_packet()
            packet = wrap_packet_securely(
                original_data,
                deployment=dep,
                sign=security_sig,
                encrypt=security_encryption,
                target_uid=security_target_universal_id
            )

            uid = self._resolved_channel.get("universal_id")

            launcher.launch(uid, packet=packet, fire_catapult=True)

        except Exception as e:
            emit_gui_exception_log("OutboundDispatcher._handle_outbound", e)
