import os, json, base64, rsa, tempfile, shutil, glob
from cryptography.fernet import Fernet

from matrix_gui.modules.vault.crypto.password_encryption import derive_key_from_password


def prune_old_backups(data_path, keep=20):
    # Remove the file extension and use os.path.normpath for portability
    base = os.path.splitext(data_path)[0]
    # Normalize the path to the expected format for glob and ensure forward slashes
    base = base.replace("\\", "/")

    # Use glob to find all backup files
    baks = sorted(glob.glob(f"{base}.*.bak"), reverse=True)

    for bak in baks[keep:]:
        try:
            os.remove(bak)
            # Convert backslashes to forward slashes for consistent output
            print(f"[VAULT] 🧹 Pruned old backup: {normalize_path(bak)}")
        except Exception as e:
            print(f"[VAULT] ⚠️ Could not remove {bak}: {e}")

def save_vault_singlefile(data: dict, password: str, data_path: str):
    """
    Safely save the vault:
      - Validate deployments (no None/junk).
      - Backup existing vault.
      - Atomic write using temp file + rename.
    """
    # --- 1. Sanitize vault ---
    try:
        deployments = data.get("deployments", {})
        for dep_id in list(deployments):
            if not isinstance(deployments[dep_id], dict):
                print(f"[VAULT] 🚮 Purged corrupt deployment {dep_id}")
                deployments.pop(dep_id, None)

        # --- 2. Encrypt as usual ---
        salt = os.urandom(16)
        fernet_key = Fernet.generate_key()
        key = derive_key_from_password(password, salt)
        fernet_for_key = Fernet(key)
        encrypted_fernet_key = fernet_for_key.encrypt(fernet_key)
        fernet = Fernet(fernet_key)
        encrypted_vault = fernet.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        bundle = {
            "kdf_salt": base64.b64encode(salt).decode(),
            "encrypted_fernet_key": base64.b64encode(encrypted_fernet_key).decode(),
            "vault": base64.b64encode(encrypted_vault).decode()
        }

        # --- 3. Backup existing vault ---
        if os.path.exists(data_path):
            backup_path = f"{data_path}.{int(os.path.getmtime(data_path))}.bak"
            try:
                shutil.copy2(data_path, backup_path)
                print(f"[VAULT] 📦 Backup created at {normalize_path(backup_path)}")
                prune_old_backups(data_path, keep=20)
            except Exception as e:
                print(f"[VAULT] ⚠️ Backup failed: {e}")

        # --- 4. Atomic write ---
        dir_name = os.path.dirname(data_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".vault_", suffix=".json")

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, data_path)  # atomic swap
        print(f"[VAULT] ✅ Saved safely to {normalize_path(data_path)}")
    except Exception as e:
        print(f"[VAULT_HANDLER_ERROR] Failed to save vault: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def load_vault_singlefile(password: str, data_path: str) -> dict:
    try:
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

        return json.loads(decrypted_data.decode("utf-8"))
    except Exception as e:
        print(f"[VAULT_HANDLER_ERROR] Failed to load vault: {e}")
        return False


def retrieve_full_vault(password: str, data_path: str) -> dict:
    # Convenience method to unify use across app
    return load_vault_singlefile(password, data_path)

def sign_payload(payload_dict: dict, password: str, data_path: str) -> str:
    try:
        vault = load_vault_singlefile(password, data_path)
        priv_pem = vault.get("local_private_key")
        if not priv_pem:
            raise RuntimeError("Local private key not found in vault.")
        priv = rsa.PrivateKey.load_pkcs1(priv_pem.encode())
        data = json.dumps(payload_dict, sort_keys=True).encode()
        sig = rsa.sign(data, priv, "SHA-256")
        return base64.b64encode(sig).decode()
    except Exception as e:
        print(f"[VAULT_HANDLER_ERROR] failed to sign payload: {e}")

def normalize_path(path: str) -> str:
    """Return a uniform, portable path."""
    return os.path.normpath(path).replace("\\", "/")

def verify_signature(payload_dict: dict, signature_b64: str, sender_name: str, password: str, data_path: str) -> bool:
    try:
        vault = load_vault_singlefile(password, data_path)
        sender_info = vault.get("trusted_servers", {}).get(sender_name)
        if not sender_info:
            print(f"[SECURITY] No pubkey for sender: {sender_name}")
            return False
        pub = rsa.PublicKey.load_pkcs1(sender_info["pubkey"].encode())
        sig = base64.b64decode(signature_b64)
        data = json.dumps(payload_dict, sort_keys=True).encode()
        rsa.verify(data, sig, pub)
        return True
    except rsa.VerificationError:
        print(f"[VAULT_HANDLER_ERROR] failed to sign payload: {e}")
        return False
