from Crypto.PublicKey import RSA
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.utils.crypto_utils import (
    verify_signed_payload,
    pem_fix,
    decrypt_with_ephemeral_aes,
)
from matrix_gui.config.boot.globals import get_sessions


class InboundDispatcher:
    def __init__(self, bus):
        self.bus = bus
        bus.on("inbound.message", self._handle_inbound)

    def _handle_inbound(self, session_id, channel, source, payload, ts=None, **_):
        try:
            ctx = get_sessions().get(session_id)
            deployment = ctx.group.get("deployment", {}) if ctx else {}

            # === 1. Serial / Author Signature Verification ===
            serial = payload.get("serial")
            if not serial:
                print("[INBOUND] ❌ Missing serial in inbound packet")
                return

            signer_pubkey_pem = None
            signing = None

            # === First check: agent root serials ===
            agents = deployment.get("agents", [])
            uid_match = None
            for agent in agents:
                if agent.get("serial") == serial:
                    uid_match = agent.get("universal_id")
                    break

            if uid_match:
                cert_block = deployment.get("certs", {}).get(uid_match, {})
                signing = cert_block.get("signing", {})
                signer_pubkey_pem = pem_fix(signing.get("pubkey"))

            if not signer_pubkey_pem:
                print(f"[INBOUND] ❌ No cert found for serial {serial}")
                return

            signer_pubkey = RSA.import_key(
                signer_pubkey_pem.encode()
                if isinstance(signer_pubkey_pem, str)
                else signer_pubkey_pem
            )

            # Verify sig on the envelope
            verify_signed_payload(payload, payload["sig"], signer_pubkey)

            # === 2. Transport / Decrypt Stage ===
            transport_uid = channel  # e.g. "matrix-https" or "websocket-relay"

            agent_priv_pem = signing.get("remote_privkey")

            inner_content = payload.get("content", {})

            if (
                isinstance(inner_content, dict)
                and "encrypted_key" in inner_content
                and agent_priv_pem
            ):
                try:
                    directive = decrypt_with_ephemeral_aes(inner_content, agent_priv_pem)

                    verified_payload = {
                        "handler": directive.get("handler",""),
                        "content": directive.get("content",{}),
                        "ts": ts,
                    }
                except Exception as e:
                    print(f"[INBOUND] ❌ Decrypt failed: {e}")
                    return
            else:
                verified_payload = {
                    "handler": payload.get("handler"),
                    "content": inner_content,
                    "ts": ts,
                }

            # === 3. Emit Verified Events ===
            handler = verified_payload.get("handler")
            scoped_handler = f"{handler}.{session_id}"

            EventBus.emit(
                f"inbound.verified.{scoped_handler}",
                session_id=session_id,
                channel=channel,
                source=source,
                payload=verified_payload,
                ts=ts,
            )

        except Exception as e:
            print(f"[INBOUND] ❌ Verification/decrypt failed: {e}")
