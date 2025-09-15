from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
class OutboundDispatcher:
    """
    Dispatches outbound messages from the GUI to the Matrix swarm.

    This class listens for 'outbound.message' events, signs the
    payloads using a private key retrieved from the vault, and routes
    the messages to the correct channel (HTTPS or WSS).
    """
    def __init__(self, bus, sessions, vault_data):
        """
        Initializes the dispatcher and sets up the event listener.

        Args:
            bus: The event bus instance for listening to messages.
            sessions: The session manager to retrieve connection contexts.
            vault_data: The vault data dictionary containing signing keys.
        """
        self.bus = bus
        self.sessions = sessions
        self.vault_data = vault_data
        self.bus.on("outbound.message", self._handle_outbound)

    def _resolve_agent_uid(self, channel, dep):
        certs = dep.get("certs", {})
        if channel in certs:
            return channel

        parts = channel.split("-")
        # progressively strip suffixes until we find a match
        while len(parts) > 1:
            parts = parts[:-1]
            candidate = "-".join(parts)
            if candidate in certs:
                return candidate
        return None

    def _resolve_channel(self, ctx, channel):
        # exact match first
        if channel in ctx.channels:
            return channel
        # try stripping session suffix
        if "-" in channel:
            base = channel.rsplit("-", 1)[0]
            if base in ctx.channels:
                return base
        # try stripping twice (handles matrix-https-xxxxxx-https)
        if channel.count("-") > 1:
            parts = channel.split("-")
            for i in range(len(parts) - 1, 0, -1):
                candidate = "-".join(parts[:i])
                if candidate in ctx.channels:
                    return candidate
        return None

    def _handle_outbound(self, session_id, channel, packet:Packet):
        try:
            ctx = get_sessions().get(session_id)
            dep = ctx.group.get("deployment", {}) if ctx else {}

            # Find the agent by channel role
            agent = None
            for a in dep.get("agents", []):
                if a.get("connection", {}).get("channel") == channel:
                    agent = a
                    break

            if not agent:
                print(f"[DISPATCHER] ❌ Channel role '{channel}' not found in deployment {dep.get('label')}")
                return

            # Resolve actual channel in session
            resolved_channel = next(
                (ch for ch in ctx.channels.keys() if ch.startswith(agent["universal_id"])),
                None
            )
            if not resolved_channel:
                print(f"[DISPATCHER] ❌ No active connector for {agent['universal_id']} in session {session_id}")
                return

            conn = ctx.channels[resolved_channel]

            conn.send(packet)  # fallback for connectors using _send

        except Exception as e:
            emit_gui_exception_log("OutboundDispatcher._handle_outbound", e)