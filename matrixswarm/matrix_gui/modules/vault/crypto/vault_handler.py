import os
import json
import base64
import rsa
from cryptography.fernet import Fernet
from matrix_gui.modules.vault.crypto.password_encryption import derive_key_from_password

def save_vault_singlefile(data: dict, password: str, data_path: str):
    # 1. Generate salt, Fernet key
    salt = os.urandom(16)
    fernet_key = Fernet.generate_key()
    # 2. Encrypt Fernet key with password+salt
    key = derive_key_from_password(password, salt)
    fernet_for_key = Fernet(key)
    encrypted_fernet_key = fernet_for_key.encrypt(fernet_key)
    # 3. Encrypt the vault data with Fernet key
    fernet = Fernet(fernet_key)
    encrypted_vault = fernet.encrypt(json.dumps(data).encode())
    # 4. Store everything in one JSON file
    bundle = {
        "kdf_salt": base64.b64encode(salt).decode(),
        "encrypted_fernet_key": base64.b64encode(encrypted_fernet_key).decode(),
        "vault": base64.b64encode(encrypted_vault).decode()
    }
    with open(data_path, "w") as f:
        json.dump(bundle, f)


def load_vault_singlefile(password: str, data_path: str) -> dict:
    with open(data_path, "r") as f:
        bundle = json.load(f)
    salt = base64.b64decode(bundle["kdf_salt"])
    encrypted_fernet_key = base64.b64decode(bundle["encrypted_fernet_key"])
    encrypted_vault = base64.b64decode(bundle["vault"])
    # Decrypt Fernet key
    key = derive_key_from_password(password, salt)
    fernet_for_key = Fernet(key)
    fernet_key = fernet_for_key.decrypt(encrypted_fernet_key)
    # Decrypt vault
    fernet = Fernet(fernet_key)
    decrypted_data = fernet.decrypt(encrypted_vault)
    return json.loads(decrypted_data)



def retrieve_full_vault(password: str, data_path: str) -> dict:
    # Convenience method to unify use across app
    return load_vault_singlefile(password, data_path)

def sign_payload(payload_dict: dict, password: str, data_path: str) -> str:
    vault = load_vault_singlefile(password, data_path)
    priv_pem = vault.get("local_private_key")
    if not priv_pem:
        raise RuntimeError("Local private key not found in vault.")
    priv = rsa.PrivateKey.load_pkcs1(priv_pem.encode())
    data = json.dumps(payload_dict, sort_keys=True).encode()
    sig = rsa.sign(data, priv, "SHA-256")
    return base64.b64encode(sig).decode()


def verify_signature(payload_dict: dict, signature_b64: str, sender_name: str, password: str, data_path: str) -> bool:
    vault = load_vault_singlefile(password, data_path)
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
