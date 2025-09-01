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
        print("[DISPATCHER][INBOUND] ✅ Armed and listening for inbound.message")

    def _handle_inbound(self, session_id, channel, source, payload, ts=None, **_):
        try:
            ctx = get_sessions().get(session_id)
            deployment = ctx.group.get("deployment", {}) if ctx else {}

            # === 1. Serial / Author Signature Verification ===
            serial = payload.get("serial")
            if not serial:
                print("[INBOUND] ❌ Missing serial in inbound packet")
                return

            # Look up signing pubkey from vault by serial
            certs = deployment.get("certs", {})
            signer_pubkey_pem = None
            for agent_uid, cert_block in certs.items():
                signing = cert_block.get("signing", {})
                if signing.get("serial") == serial:
                    signer_pubkey_pem = pem_fix(
                        signing.get("pubkey") or signing.get("remote_pubkey")
                    )
                    break

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
                        "handler": directive.get("handler"),  # ✅ handler comes from decrypted body
                        "content": directive.get("content", directive),
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

            if handler:
                EventBus.emit(
                    f"inbound.verified.{handler}",
                    session_id=session_id,
                    channel=channel,
                    source=source,
                    payload=verified_payload,
                    ts=ts,
                )

                # also wildcard events for namespace
                parts = handler.split(".")
                for i in range(1, len(parts)):
                    ns = ".".join(parts[:i]) + ".*"
                    EventBus.emit(
                        f"inbound.verified.{ns}",
                        session_id=session_id,
                        channel=channel,
                        source=source,
                        payload=verified_payload,
                        ts=ts,
                    )

        except Exception as e:
            print(f"[INBOUND] ❌ Verification/decrypt failed: {e}")
