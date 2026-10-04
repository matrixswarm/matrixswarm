# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import json
from matrix_gui.core.utils.packet_freshness import packet_is_fresh
_PACKET_TTL = 314  # seconds for normal transient packets

from Crypto.PublicKey import RSA
from matrix_gui.core.utils.crypto_utils import verify_signed_payload, decrypt_with_ephemeral_aes

def unwrap_secure_packet(outer_packet: dict, remote_pubkey, local_privkey, logger=None):
    """
    Securely unwraps a signed and encrypted packet.

    Options:
        - allow_unsigned: allows packets without a signature (default: False)
        - allow_unencrypted: allows plaintext content (default: True)

    Returns:
        inner_packet (dict) if valid, else False.
    """
    try:

        outer_content = outer_packet.get("content", {})

        if not isinstance(outer_content, dict):
            if logger:
                logger(f"[SECURE][REJECT] outer content not dict: {type(outer_content)}")
            return False

        # Signature check
        sig = outer_content.get("sig")
        try:
            if not verify_signed_payload({k: v for k, v in outer_content.items() if k != "sig"}, sig, ensure_rsa_key(remote_pubkey)):
                return False
            timestamp = outer_content.get("timestamp", 0)
            sig = outer_content.get("sig")
            expires = outer_content.get("expires")
            if not packet_is_fresh(timestamp, window=_PACKET_TTL, expires=expires):
                if logger:
                    logger("[SECURE][TIMESTAMP] Stale, expired, or invalid packet timestamp.")
                return False

        except Exception as e:
            if logger:
                logger(f"[SECURE][REJECT] Signature verification failed: {type(e).__name__} – {e}")
            return False

        # Get the contents of the inner packet
        inner = outer_content.get("content")

        # decrypt it
        try:
            inner = decrypt_with_ephemeral_aes(inner, local_privkey)
            if isinstance(inner, str):
                inner = json.loads(inner)

        except Exception as e:
            if logger:
                logger(f"[SECURE][REJECT] AES decrypt failed or malformed JSON: {e}")
            return False

        return inner

    except Exception as e:
        if logger:
            logger(f"[SECURE][FAIL] unwrap failed: {type(e).__name__}: {e}")
        return False

def ensure_rsa_key(key):

    if isinstance(key, str):
        return RSA.import_key(key.encode())
    return key
