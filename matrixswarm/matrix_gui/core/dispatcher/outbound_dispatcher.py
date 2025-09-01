import json, base64
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

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

    def _handle_outbound(self, **kwargs):
        try:
            session_id = kwargs.get("session_id")
            channel = kwargs.get("channel")
            payload = kwargs.get("payload")

            if not session_id or not channel or not payload:
                print(f"[DISPATCHER] ❌ outbound.message missing fields: {kwargs}")
                return

            ctx = self.sessions.get(session_id)
            if not ctx:
                print(f"[DISPATCHER] ❌ No session {session_id}")
                return

            # parse agent uid from channel name
            agent_uid = channel.rsplit("-", 1)[0] if "-" in channel else None
            dep = ctx.group.get("deployment", {})
            signing_key = None

            if agent_uid:
                try:
                    priv_pem = (
                        dep.get("certs", {})
                        .get(agent_uid, {})
                        .get("signing", {})
                        .get("remote_privkey")
                    )
                    if priv_pem:
                        signing_key = RSA.import_key(priv_pem.encode())
                except Exception as e:
                    print(f"[DISPATCHER] ❌ Failed to load signing key for {agent_uid}: {e}")

            if channel.endswith("https"):
                # wrap payload

                sig = self._sign_payload(payload, signing_key)
                outer = {"sig": sig, "content": payload}
                self._send(session_id, channel, outer)
            else:
                self._send(session_id, channel, payload)

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
