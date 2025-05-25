import json
import base64
import tempfile
import os
import hashlib
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa

def encrypt_vault(payload_dict, output_path=None):
    key = get_random_bytes(32)
    cipher = AES.new(key, AES.MODE_GCM)

    def safe_pem(k):
        if isinstance(k, str):
            return k
        if hasattr(k, "public_bytes"):
            return k.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode()
        if hasattr(k, "private_bytes"):
            return k.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode()
        return k

    keys = payload_dict.get("secure_keys")
    if not keys:
        raise RuntimeError("[VAULT] secure_keys missing from payload.")

    keys["pub"] = safe_pem(keys["pub"])
    keys["priv"] = safe_pem(keys["priv"])
    payload_dict["secure_keys"] = keys

    data = json.dumps(payload_dict).encode()
    ciphertext, tag = cipher.encrypt_and_digest(data)

    vault = {
        "nonce": base64.b64encode(cipher.nonce).decode(),
        "tag": base64.b64encode(tag).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode()
    }

    if output_path:
        with open(output_path, "w") as f:
            json.dump(vault, f)
        vault_file_path = output_path
    else:
        vault_file = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix=".vault", prefix="agent_ghost_")
        json.dump(vault, vault_file)
        vault_file.close()
        vault_file_path = vault_file.name

    return {
        "key_b64": base64.b64encode(key).decode(),
        "vault_path": vault_file_path
    }


def decrypt_vault():
    vault_path = os.getenv("VAULTFILE")
    symkey_b64 = os.getenv("SYMKEY")
    if not vault_path or not symkey_b64:
        raise RuntimeError("[GHOST-VAULT] Missing VAULTFILE or SYMKEY.")

    key = base64.b64decode(symkey_b64)
    with open(vault_path, "r") as f:
        vault = json.load(f)

    cipher = AES.new(key, AES.MODE_GCM, nonce=base64.b64decode(vault["nonce"]))
    decrypted = cipher.decrypt_and_verify(
        base64.b64decode(vault["ciphertext"]),
        base64.b64decode(vault["tag"])
    )
    # os.remove(vault_path)  # optionally delete after boot
    payload = json.loads(decrypted.decode())

    keys = payload.get("secure_keys")
    if not keys:
        raise RuntimeError("[GHOST-VAULT] secure_keys block missing.")

    payload["public_key_obj"] = serialization.load_pem_public_key(keys["pub"].encode())
    payload["private_key_obj"] = serialization.load_pem_private_key(keys["priv"].encode(), password=None)
    payload["cached_pem"] = {"pub": keys["pub"], "priv": keys["priv"]}
    payload["pub_fingerprint"] = hashlib.sha256(keys["pub"].encode()).hexdigest()[:12]

    return payload


def build_encrypted_spawn_env(payload_dict, output_path=None):
    result = encrypt_vault(payload_dict, output_path)

    env = os.environ.copy()
    env.update({
        "SYMKEY": result["key_b64"],
        "VAULTFILE": result["vault_path"]
    })

    return env


# 🧠 Utility to generate agent's cryptographic keypair
def generate_agent_keypair():
    priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_key = priv_key.public_key()

    priv_pem = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()

    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()

    return {
        "priv": priv_pem,
        "pub": pub_pem
    }


def fingerprint(pub):
    if pub is None:
        return "None"
    if isinstance(pub, str):
        pub_bytes = pub.encode()
    else:
        pub_bytes = pub.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo
        )
    return hashlib.sha256(pub_bytes).hexdigest()[:12]
