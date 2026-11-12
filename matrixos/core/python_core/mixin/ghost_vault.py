import json
import base64
import os
import hashlib
import stat
import tempfile
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from core.python_core.safe_paths import open_beneath, write_file_at


def generate_agent_keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key()

    return {
        "priv": priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode(),
        "pub": pub.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
    }


def fingerprint(pub):
    pub_bytes = pub.encode() if isinstance(pub, str) else pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(pub_bytes).hexdigest()[:12]


def _safe_pem(k):
    if isinstance(k, str):
        return k
    if hasattr(k, "public_bytes"):
        return k.public_bytes(serialization.Encoding.PEM,
                              serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    if hasattr(k, "private_bytes"):
        return k.private_bytes(serialization.Encoding.PEM,
                               serialization.PrivateFormat.PKCS8,
                               encryption_algorithm=serialization.NoEncryption()).decode()
    return k

def encrypt_vault(payload_dict, output_path=None, *, output_dir_fd=None):

    try:

        key = get_random_bytes(32)
        cipher = AES.new(key, AES.MODE_GCM)

        # Ensure keys are PEM
        keys = payload_dict.get("secure_keys", {})
        keys["pub"] = _safe_pem(keys.get("pub"))
        keys["priv"] = _safe_pem(keys.get("priv"))
        payload_dict["secure_keys"] = keys

        # Hash just the payload_dict, not the wrapper
        payload_json = json.dumps(payload_dict, sort_keys=True).encode()
        payload_sha = hashlib.sha256(payload_json).hexdigest()

        envelope = {
            "sha256": payload_sha,
            "payload": payload_dict
        }

        data = json.dumps(envelope).encode()
        ciphertext, tag = cipher.encrypt_and_digest(data)

        vault = {
            "nonce": base64.b64encode(cipher.nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode()
        }

        # Save if path provided
        if output_dir_fd is not None:
            if not output_path:
                raise ValueError("A vault filename is required with an anchored directory")
            vault_name = os.path.basename(output_path)
            if not vault_name or vault_name in (".", ".."):
                raise ValueError("Invalid vault filename")
            write_file_at(output_dir_fd, vault_name, json.dumps(vault).encode("utf-8"), mode=0o600)
            # The child must inherit output_dir_fd. This keeps the vault tied
            # to the opened pod even if an ancestor is renamed or replaced.
            vault_path = f"/proc/self/fd/{output_dir_fd}/{vault_name}"
        else:
            vault_path = output_path or tempfile.NamedTemporaryFile(delete=False, mode='w', suffix=".vault", prefix="agent_ghost_").name
            with open(vault_path, "w", encoding="utf-8") as f:
                json.dump(vault, f)

        return {
            "key_b64": base64.b64encode(key).decode(),
            "vault_path": vault_path,
            "vault_dir_fd": output_dir_fd,
        }

    except Exception as e:
        raise RuntimeError(f"[VAULT][ERROR] Failed to write vault to disk: {e}")


def decrypt_vault(log=None):

    directory_fd = None
    try:
        vault_path = os.getenv("VAULTFILE")
        symkey_b64 = os.getenv("SYMKEY")
        if not vault_path or not symkey_b64:
            raise RuntimeError("[GHOST-VAULT] Missing VAULTFILE or SYMKEY.")

        key = base64.b64decode(symkey_b64)
        pinned = os.getenv("MATRIX_VAULT_DIR_FD")
        if pinned is not None:
            directory_fd = int(pinned)
            if directory_fd < 3 or not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
                raise ValueError("Invalid pinned vault directory")
            vault_name = os.path.basename(vault_path)
            if vault_path != f"/proc/self/fd/{directory_fd}/{vault_name}":
                raise ValueError("Invalid pinned vault path")
            fd = open_beneath(directory_fd, vault_name, os.O_RDONLY | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Unsafe pinned vault")
                vault_identity = (info.st_dev, info.st_ino)
                with os.fdopen(fd, "r", encoding="utf-8") as f:
                    fd = -1
                    vault = json.load(f)
            finally:
                if fd >= 0:
                    os.close(fd)
        else:
            with open(vault_path, "r", encoding="utf-8") as f:
                vault = json.load(f)

        cipher = AES.new(key, AES.MODE_GCM, nonce=base64.b64decode(vault["nonce"]))
        decrypted = cipher.decrypt_and_verify(
            base64.b64decode(vault["ciphertext"]),
            base64.b64decode(vault["tag"])
        )

        envelope = json.loads(decrypted.decode())

        payload_dict = envelope.get("payload")
        expected_sha = envelope.get("sha256")

        if not payload_dict or not expected_sha:
            raise RuntimeError("[GHOST-VAULT] Malformed vault envelope.")

        actual_sha = hashlib.sha256(json.dumps(payload_dict, sort_keys=True).encode()).hexdigest()
        if actual_sha != expected_sha:
            raise RuntimeError(f"[GHOST-VAULT] SHA256 MISMATCH! Expected {expected_sha}, got {actual_sha}")

        # Load key objects
        keys = payload_dict.get("secure_keys", {})
        payload_dict["public_key_obj"] = serialization.load_pem_public_key(keys["pub"].encode())
        payload_dict["private_key_obj"] = serialization.load_pem_private_key(keys["priv"].encode(), password=None)
        payload_dict["cached_pem"] = {"pub": keys["pub"], "priv": keys["priv"]}
        payload_dict["pub_fingerprint"] = fingerprint(keys["pub"])

        # ─── TRUST PAYLOAD EXTRACTION ───
        keys = payload_dict.get("secure_keys", {})

        payload_dict["pub_fingerprint"] = fingerprint(keys["pub"])
        payload_dict["cached_pem"] = {
            "pub": keys["pub"],
            "priv": keys["priv"]
        }

        # 🟢 Own key objects
        payload_dict["public_key_obj"] = serialization.load_pem_public_key(keys["pub"].encode())
        payload_dict["private_key_obj"] = serialization.load_pem_private_key(keys["priv"].encode(), password=None)

        # 🧬 Swarm AES Key
        payload_dict["swarm_key"] = payload_dict.get("swarm_key")

        # Agent personal AES key or maybe not ;)
        payload_dict["private_key"] = payload_dict.get("private_key")

        payload_dict["encryption_enabled"] = payload_dict.get("encryption_enabled")

        # 🧠 Matrix-level keys
        matrix_pub = payload_dict.get("matrix_pub")

        matrix_priv = payload_dict.get("matrix_priv")

        payload_dict["matrix_priv"] = matrix_priv

        payload_dict["matrix_pub_obj"] = serialization.load_pem_public_key(matrix_pub.encode())

        payload_dict["matrix_priv_obj"] = None
        if matrix_priv:
            payload_dict["matrix_priv_obj"] = serialization.load_pem_private_key(
                matrix_priv.encode(),
                password=None,
            )

        if pinned is not None:
            current = os.stat(vault_name, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != vault_identity:
                raise ValueError("Pinned vault changed before cleanup")
            os.unlink(vault_name, dir_fd=directory_fd)
        else:
            os.remove(vault_path)

    except Exception as e:

        raise RuntimeError(f"[VAULT][ERROR] Final trust unpack failed: {e}")
    finally:
        if directory_fd is not None and directory_fd >= 3 and os.getenv("MATRIX_VAULT_CLOSE_DIR_FD") == "1":
            try:
                os.close(directory_fd)
            except OSError:
                pass

    return payload_dict

def build_encrypted_spawn_env(payload_dict, output_path=None, *, output_dir_fd=None):
    result = encrypt_vault(payload_dict, output_path, output_dir_fd=output_dir_fd)
    env = {
        **os.environ,
        "SYMKEY": result["key_b64"],
        "VAULTFILE": result["vault_path"]
    }
    if result["vault_dir_fd"] is None:
        env.pop("MATRIX_VAULT_DIR_FD", None)
        env.pop("MATRIX_VAULT_CLOSE_DIR_FD", None)
    else:
        env["MATRIX_VAULT_DIR_FD"] = str(result["vault_dir_fd"])
        env["MATRIX_VAULT_CLOSE_DIR_FD"] = "1"
    return env


def sign_pubkey_registry(self, pubkey_path):
    try:
        with open(pubkey_path, "rb", encoding="utf-8") as f:
            data = f.read()

        signature = self.private_key_obj.sign(
            data,
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        with open(pubkey_path + ".sig", "wb", encoding="utf-8") as sig_file:
            sig_file.write(signature)

        self.log("[VAULT] Registry signed successfully.")
    except Exception as e:
        self.log(f"[VAULT][SIGN ERROR] {e}")


def verify_pubkey_registry(self):
    try:
        pubkey_path = os.path.join(
            self.path_resolution["comm_path"],
            self.get_matrix_universal_id(),
            "pubkeys.json",
        )
        sig_path = pubkey_path + ".sig"

        if not os.path.exists(pubkey_path) or not os.path.exists(sig_path):
            self.log("[VAULT] Registry or signature missing.")
            return

        with open(pubkey_path, "rb", encoding="utf-8") as f:
            data = f.read()
        with open(sig_path, "rb", encoding="utf-8") as s:
            signature = s.read()

        self.public_key_obj.verify(
            signature,
            data,
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        self.log("[VAULT] Registry signature verified.")
    except Exception as e:
        self.log(f"[VAULT][VERIFY ERROR] Signature invalid or tampered: {e}")
