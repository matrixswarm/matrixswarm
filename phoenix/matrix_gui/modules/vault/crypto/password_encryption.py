import os
import base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

def generate_fernet_key():
    return Fernet.generate_key()

def derive_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
        backend=default_backend()
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

def encrypt_fernet_key_with_password(fernet_key: bytes, password: str, key_path: str) -> bytes:
    salt = os.urandom(16)
    key = derive_key_from_password(password, salt)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(fernet_key)

    with open(key_path, "wb") as f:
        f.write(salt + encrypted)

    return key


def decrypt_fernet_key_with_password(password: str, key_path: str) -> bytes:
    if not os.path.exists(key_path):
        raise FileNotFoundError(f"Encrypted Fernet key file not found: {key_path}")

    with open(key_path, "rb") as f:
        raw = f.read()

    salt = raw[:16]
    encrypted = raw[16:]
    key = derive_key_from_password(password, salt)
    fernet = Fernet(key)
    decrypted = fernet.decrypt(encrypted)
    return decrypted