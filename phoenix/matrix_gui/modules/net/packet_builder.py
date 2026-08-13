# matrix_gui/modules/net/packet_builder.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import json, time, secrets, base64

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Hash import SHA256
from Crypto.Signature import pkcs1_15, pss

DEFAULT_SIG_ALG = "RSASSA-PKCS1v1_5"   # flip to "RSASSA-PSS" when server verify is ready
AEAD_ALG = "AES-GCM"
KEY_WRAP_ALG = "RSA-OAEP-SHA256"

def _canon_bytes(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()

def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()

@dataclass
class SigningKeyset:
    inner_sign_priv_pem: str        # GUI Matrix signing private key (inner sig)
    recipient_pub_pem: str          # Matrix RSA PUBLIC key (wrap ephemeral AES key)
    outer_sign_priv_pem: str        # GUI HTTPS signing private key (outer sig)
    inner_kid: Optional[str] = None
    recipient_kid: Optional[str] = None
    outer_kid: Optional[str] = None

@dataclass
class SigAlg:
    name: str = DEFAULT_SIG_ALG
    def sign_b64(self, priv_pem: str, obj: Dict[str, Any]) -> str:
        key = RSA.import_key(priv_pem.encode())
        h = SHA256.new(_canon_bytes(obj))
        if self.name == "RSASSA-PSS":
            sig = pss.new(key).sign(h)
        else:
            sig = pkcs1_15.new(key).sign(h)
        return _b64e(sig)

class PacketBuilder:
    def __init__(self, inner_sig_alg: SigAlg | None = None, outer_sig_alg: SigAlg | None = None):
        self.inner_alg = inner_sig_alg or SigAlg()
        self.outer_alg = outer_sig_alg or SigAlg()

    def build_external_embedded(
        self,
        session_id: str,
        inner_handler: str,
        content: Dict[str, Any],
        keys: SigningKeyset,
        ts: float | None = None,
        include_alg_markers: bool = True
    ) -> Dict[str, Any]:
        ts = ts or time.time()

        # 1) inner: add session_id, sign
        inner_core = {"ts": ts, "handler": inner_handler, "content": content, "session_id": session_id}
        inner_plain = dict(inner_core)
        if include_alg_markers: inner_plain["salg"] = self.inner_alg.name
        if keys.inner_kid: inner_plain["ikid"] = keys.inner_kid
        inner_sig_b64 = self.inner_alg.sign_b64(keys.inner_sign_priv_pem, inner_core)
        inner_plain["sig"] = inner_sig_b64

        # 2) encrypt inner with AES-256-GCM (ephemeral)
        aes_key = secrets.token_bytes(32)
        iv = secrets.token_bytes(12)
        cipher = AES.new(aes_key, AES.MODE_GCM, nonce=iv)
        ct, tag = cipher.encrypt_and_digest(_canon_bytes(inner_plain))

        # 3) wrap AES key with Matrix RSA pub (OAEP-SHA256)
        pub = RSA.import_key(keys.recipient_pub_pem.encode())
        oaep = PKCS1_OAEP.new(pub, hashAlgo=SHA256)
        ek = oaep.encrypt(aes_key)

        matrix_encrypted = {
            "aead": AEAD_ALG,
            "iv": _b64e(iv),
            "ct": _b64e(ct),
            "tag": _b64e(tag),
            "ek": _b64e(ek),
            "kalg": KEY_WRAP_ALG
        }
        if keys.recipient_kid: matrix_encrypted["rkid"] = keys.recipient_kid

        # 4) outer: fixed handler + encrypted content, sign
        outer_core = {"ts": ts, "handler": "external_embedded", "content": matrix_encrypted}
        outer_packet = dict(outer_core)
        if include_alg_markers: outer_packet["salg"] = self.outer_alg.name
        if keys.outer_kid: outer_packet["okid"] = keys.outer_kid
        outer_sig_b64 = self.outer_alg.sign_b64(keys.outer_sign_priv_pem, outer_core)
        outer_packet["sig"] = outer_sig_b64
        return outer_packet
