import os
import base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

FERNET_KEY_RAW = "matrix_gui/keys/fernet.key"
FERNET_KEY_ENC = "matrix_gui/keys/fernet.key.enc"

def derive_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
        backend=default_backend()
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

def encrypt_fernet_key_with_password(password: str):
    # ✅ Generate new Fernet key if it doesn't exist
    if not os.path.exists(FERNET_KEY_RAW):
        key = Fernet.generate_key()
        with open(FERNET_KEY_RAW, "wb") as f:
            f.write(key)

    with open(FERNET_KEY_RAW, "rb") as f:
        fernet_key = f.read()

    salt = os.urandom(16)
    key = derive_key_from_password(password, salt)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(fernet_key)

    with open(FERNET_KEY_ENC, "wb") as f:
        f.write(salt + encrypted)

    os.remove(FERNET_KEY_RAW)

    return key

def decrypt_fernet_key_with_password(password: str) -> bytes:
    print("[DEBUG] decrypt_fernet_key_with_password(): START")

    if not os.path.exists(FERNET_KEY_ENC):
        print("[DEBUG] Encrypted key file missing.")
        raise FileNotFoundError("Encrypted Fernet key file not found.")

    print(f"[DEBUG] Opening {FERNET_KEY_ENC}")
    with open(FERNET_KEY_ENC, "rb") as f:
        raw = f.read()

    print(f"[DEBUG] Encrypted key file length: {len(raw)}")
    if len(raw) <= 16:
        print("[DEBUG] Encrypted key file too short.")
        raise ValueError("Encrypted Fernet key file is malformed or truncated.")

    salt = raw[:16]
    encrypted = raw[16:]
    print(f"[DEBUG] Salt extracted: {salt.hex()}")
    print(f"[DEBUG] Encrypted blob length: {len(encrypted)}")

    key = derive_key_from_password(password, salt)
    print(f"[DEBUG] Derived key (base64): {base64.urlsafe_b64encode(key).decode()}")

    try:
        fernet = Fernet(key)
        print("[DEBUG] Fernet object created. Attempting decryption...")
        decrypted = fernet.decrypt(encrypted)
        print("[DEBUG] Decryption successful.")
        if len(decrypted) != 32:
            print("[DEBUG] Decrypted key wrong length.")
            raise ValueError("Decrypted key length is invalid.")
        return decrypted
    except Exception as e:
        print(f"[DEBUG] Decryption failed: {type(e).__name__}: {e}")
        raise ValueError("Fernet decryption failed. Possibly wrong password or corrupt key.")