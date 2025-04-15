import os
import threading
import uuid
import time
import json
import traceback
import hashlib
import importlib
import subprocess
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding

def get_secret_key():
    path = os.path.join(os.environ.get("AGENT_ROOT", "/sites/orbit/python"), "secret.key")
    with open(path, "rb") as f:
        return f.read()

def write_handshake_status(agent_dir, status_data):
    """
    Writes status.json and performs the hello token handshake in one call.

    Parameters:
    - agent_dir (str): Full path to the agent’s pod directory.
    - status_data (dict): Agent identity + status data.
    """
    try:
        # Paths
        status_path = os.path.join(agent_dir, "status.json")
        token_path = os.path.join(agent_dir, "hello.token")

        # Add/Update key timestamp fields
        now = time.time()
        status_data.setdefault("uuid", "unknown-agent")
        status_data["last_hello"] = now
        status_data.setdefault("started_at", now)
        status_data["status"] = "alive"

        # Write status.json
        with open(status_path, "w") as f:
            json.dump(status_data, f, indent=2)

        # Handshake: Touch hello.token (used by inotify/Sentinel)
        with open(token_path, 'a'):
            os.utime(token_path, None)

        print(f"[HANDSHAKE] Status written + hello.token touched for {status_data['uuid']}")
    except Exception as e:
        print(f"[HANDSHAKE][ERROR] Failed to update status or complete handshake: {e}")

def log_message(self, uuid, severity, message, pod_root="/agents"):
    try:
        # Hash the message content
        body = f"severity: {severity}\nmessage: {message}"
        hash_str = hashlib.sha256(body.encode("utf-8")).hexdigest()
        timestamp = int(time.time())

        # Construct the mailman drop path
        mailman_log_dir = os.path.join(pod_root, "mailman-core", "log")
        os.makedirs(mailman_log_dir, exist_ok=True)

        # Final log file name
        filename = f"{timestamp}_{hash_str}_{uuid}.msg"
        filepath = os.path.join(mailman_log_dir, filename)

        # Write the message
        with open(filepath, "w") as f:
            f.write(body)

        print(f"[CORE] Message logged to mailman: {filename}")
        return hash_str

    except Exception as e:
        print(f"[CORE-ERROR] Failed to log message to mailman: {e}")

#standizes the path
def get_agent_pod_path(uuid):
    """
    Dynamically resolves the full pod path for a given agent UUID using AGENT_ROOT.
    """
    agent_root = os.environ.get("AGENT_ROOT", "/sites/orbit/python")
    pod_path = os.path.join(agent_root, "pod", uuid)
    os.makedirs(pod_path, exist_ok=True)
    return pod_path

def generate_uuid_from_permanent_id(permanent_id):
    short = str(uuid.uuid4())[:8]
    return f"{permanent_id}-{short}"

class ProtectedCore:
    def __init__(self, encryption_key: bytes):
        self._encryption_key = encryption_key

    def encrypt(self, data: bytes) -> bytes:
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data) + padder.finalize()

        cipher = Cipher(algorithms.AES(self._encryption_key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded_data) + encryptor.finalize()
        return iv + encrypted

    def decrypt(self, encrypted_data: bytes) -> bytes:
        iv = encrypted_data[:16]
        encrypted = encrypted_data[16:]

        cipher = Cipher(algorithms.AES(self._encryption_key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(encrypted) + decryptor.finalize()

        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(padded_data) + unpadder.finalize()

    def get_key(self):
        raise PermissionError("Direct access to encryption key is forbidden.")

