import os
import json
import base64
import rsa
from cryptography.fernet import Fernet
from matrix_gui.crypto.password_encryption import decrypt_fernet_key_with_password

VAULT_PATH = "matrix_gui/keys/vault.json"
FERNET_KEY_PATH = "matrix_gui/keys/fernet.key"

def _ensure_fernet_key(password: str):
    from matrix_gui.crypto.password_encryption import decrypt_fernet_key_with_password
    key = decrypt_fernet_key_with_password(password)
    return Fernet(key)


def save_vault(data: dict, password: str):
    from matrix_gui.crypto.password_encryption import decrypt_fernet_key_with_password
    key = decrypt_fernet_key_with_password(password)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(json.dumps(data, indent=2).encode())
    with open(VAULT_PATH, "wb") as f:
        f.write(encrypted)

def handle_view_vault(self):
    try:
        vault = load_vault()
        info = []

        if vault.get("local_public_key"):
            info.append("🔐 Local Keypair: ✅")

        if "trusted_servers" in vault:
            info.append("🌐 Trusted Servers:")
            for name, srv in vault["trusted_servers"].items():
                ip = srv.get("ip", "???")
                port = srv.get("port", "???")
                info.append(f"  - {name} @ {ip}:{port}")

        if not info:
            info.append("⚠️ Vault is empty.")

        self.output.append("\n".join(info))

    except Exception as e:
        self.output.append(f"❌ Failed to load vault: {e}")

def load_vault(password: str = None) -> dict:
    if not os.path.exists(VAULT_PATH):
        print("[VAULT] No vault found.")
        raise FileNotFoundError("Vault does not exist.")
    from matrix_gui.crypto.password_encryption import decrypt_fernet_key_with_password
    try:
        key = decrypt_fernet_key_with_password(password)
        fernet = Fernet(key)
        with open(VAULT_PATH, "rb") as f:
            raw = f.read()
        return json.loads(fernet.decrypt(raw))
    except Exception as e:
        print(f"[VAULT][ERROR] {e}")
        raise


def generate_local_keypair(password: str):
    (pub, priv) = rsa.newkeys(2048)
    vault = load_vault(password)
    vault["local_private_key"] = priv.save_pkcs1().decode()
    vault["local_public_key"] = pub.save_pkcs1().decode()
    save_vault(vault, password)
    return pub, priv

def add_trusted_server(name: str, ip: str, port: int, pubkey_pem: str, password: str):
    vault = load_vault(password)
    vault.setdefault("trusted_servers", {})
    vault["trusted_servers"][name] = {
        "ip": ip,
        "port": port,
        "pubkey": pubkey_pem
    }
    save_vault(vault, password)

def sign_payload(payload_dict: dict) -> str:
    vault = load_vault()
    priv_pem = vault.get("local_private_key")
    if not priv_pem:
        raise RuntimeError("Local private key not found in vault.")
    priv = rsa.PrivateKey.load_pkcs1(priv_pem.encode())
    data = json.dumps(payload_dict, sort_keys=True).encode()
    sig = rsa.sign(data, priv, "SHA-256")
    return base64.b64encode(sig).decode()

def verify_signature(payload_dict: dict, signature_b64: str, sender_name: str) -> bool:
    vault = load_vault()
    sender_info = vault.get("trusted_servers", {}).get(sender_name)
    if not sender_info:
        print(f"[SECURITY] No pubkey for sender: {sender_name}")
        return False
    pub = rsa.PublicKey.load_pkcs1(sender_info["pubkey"].encode())
    sig = base64.b64decode(signature_b64)
    data = json.dumps(payload_dict, sort_keys=True).encode()
    try:
        rsa.verify(data, sig, pub)
        return True
    except rsa.VerificationError:
        return False
