import time
import json
import base64
import hashlib
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes

class PacketCryptoMixin:

    def normalize_packet(self, packet_obj):
        """
        Normalize input packet to a dict for processing.
        - If it's a packet-like object, extract with .get_packet().
        - If it's a dict, return as-is.
        - If it's a string, return wrapped in a dict under 'message'.
        """
        if hasattr(packet_obj, "get_packet"):
            return packet_obj.get_packet()
        elif isinstance(packet_obj, dict):
            return packet_obj
        elif isinstance(packet_obj, str):
            return {"message": packet_obj}
        else:
            raise TypeError("[ENCRYPTION] Unsupported packet format for encryption.")

    def encrypt_packet(self, packet_obj, key: bytes, priv_key=None) -> dict:

        if not hasattr(packet_obj, "get_packet"):
            raise TypeError("[ENCRYPTION] encrypt_packet expected a packet-like object with get_packet()")

        subpacket = self.normalize_packet(packet_obj)

        # Create a wrapper payload to hold metadata and subpacket
        payload = {
            "timestamp": int(time.time()),
            "subpacket": subpacket
        }

        if priv_key:
            sig = self.sign_payload(payload, priv_key)
            payload["sig"] = sig

        raw = json.dumps(payload, sort_keys=True).encode()

        nonce = get_random_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(raw)

        return {
            "type": "encrypted_blob",
            "cipher": "AES-GCM",
            "encoding": "base64",
            "timestamp": int(time.time()),
            "nonce": base64.b64encode(nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
            "payload": base64.b64encode(ciphertext).decode()
        }

    def decrypt_packet(self, blob: dict, key: bytes, pub_key=None) -> dict:

        if blob.get("type") != "encrypted_blob":
            raise ValueError("Unsupported or unrecognized packet type.")

        nonce = base64.b64decode(blob["nonce"])
        tag = base64.b64decode(blob["tag"])
        ciphertext = base64.b64decode(blob["payload"])

        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        decrypted = cipher.decrypt_and_verify(ciphertext, tag)

        payload = json.loads(decrypted.decode())

        if pub_key:
            if "sig" not in payload:
                raise ValueError("[VERIFY] Packet missing signature; rejected.")

            self.verify_payload(payload, payload["sig"], pub_key)

        # Return only the original subpacket by default, or return the whole payload if preferred
        return payload.get("subpacket", {})


    def sign_payload(self, payload: dict, private_key) -> str:
        """
        Sign a JSON payload with a private key. Returns base64 signature string.
        """
        payload_bytes = json.dumps(payload, sort_keys=True).encode()

        signature = private_key.sign(
            payload_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )

        return base64.b64encode(signature).decode()

    def verify_payload(self, payload: dict, signature_b64: str, public_key) -> bool:
        """
        Verify a signed JSON payload with a public key.
        Returns True if valid, raises exception on failure.
        """
        try:
            signature = base64.b64decode(signature_b64)
            payload_copy = dict(payload)
            if "sig" in payload_copy:
                del payload_copy["sig"]

            payload_bytes = json.dumps(payload_copy, sort_keys=True).encode()

            public_key.verify(
                signature,
                payload_bytes,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )

            return True

        except Exception as e:
            raise ValueError(f"[VERIFY] Signature check failed: {e}")

