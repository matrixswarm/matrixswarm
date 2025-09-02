import json, base64
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.config.boot.globals import get_sessions
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


    def _sign_payload(self, packet: dict, key):
        """
        Generates a digital signature for a packet using a private key.

        The packet is first serialized to a canonical JSON string, then
        hashed and signed with RSASSA-PKCS1-v1_5.

        Args:
            packet: The dictionary payload to be signed.
            key: The RSA private key object.

        Returns:
            The base64-encoded signature string.
        """
        canon = json.dumps(packet, separators=(",", ":"), sort_keys=True).encode()
        h = SHA256.new(canon)
        sig = pkcs1_15.new(key).sign(h)
        return base64.b64encode(sig).decode()

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

    def _handle_outbound(self, session_id, channel, payload):
        try:
            ctx = get_sessions().get(session_id)
            dep = ctx.group.get("deployment", {})

            agent_uid = self._resolve_agent_uid(channel, dep)
            signing_key = None

            if agent_uid:
                priv_pem = dep.get("certs", {}).get(agent_uid, {}).get("signing", {}).get("remote_privkey")
                if priv_pem:
                    signing_key = RSA.import_key(priv_pem.encode())

            if channel.endswith("https"):
                if signing_key:
                    sig = self._sign_payload(payload, signing_key)
                    outer = {"sig": sig, "content": payload}
                else:
                    print(f"[DISPATCHER] ⚠️ No signing key for {channel} (agent_uid={agent_uid}), sending unsigned")
                    outer = {"content": payload}
                self._send(session_id, channel, outer)

        except Exception as e:
            emit_gui_exception_log("OutboundDispatcher._handle_outbound", e)

    def _send(self, session_id, channel, packet):
        ctx = self.sessions.get(session_id)
        if not ctx:
            print(f"[DISPATCHER] ❌ No session {session_id}")
            return
        conn = ctx.channels.get(channel)
        if not conn:
            print(f"[DISPATCHER] ❌ No channel {channel} in session {session_id}")
            return

        try:
            body = json.dumps(packet, separators=(",", ":")).encode()

            if channel.endswith("-https"):
                conn.request("POST", "/matrix", body=body,
                             headers={"Content-Type": "application/json"})
                resp = conn.getresponse()
                data = resp.read().decode(errors="ignore")
                print(f"[DISPATCHER] 🚀 Sent {packet.get('handler')} → HTTPS {resp.status}")
                if data:
                    print(f"[DISPATCHER] ↩️ Response: {data[:200]}")

            elif channel.endswith("-wss"):
                conn.send(body)
                print(f"[DISPATCHER] 🚀 Sent {packet.get('handler')} → WSS")

        except Exception as e:
            print(f"[DISPATCHER] ❌ Send error {e}")
