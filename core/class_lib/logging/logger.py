import time
import os
import json
import base64
from Crypto.Cipher import AES        # ← will fail if Cryptodome is installed as separate
from Crypto.Random import get_random_bytes
from core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG

class Logger:
    def __init__(self, log_path, logs="logs", file_name="agent.log"):
        if ENCRYPTION_CONFIG.is_enabled():
            swarm_key = ENCRYPTION_CONFIG.get_swarm_key()
            self._decoded_swarm_key = base64.b64decode(swarm_key) if swarm_key else b''
        self.default_log_file = os.path.join(log_path, logs, file_name)
        os.makedirs(os.path.dirname(self.default_log_file), exist_ok=True)

    def log(
            self,
            message,
            level="INFO",
            print_to_console=True,
            include_timestamp=True,
            override_path=None,
            override_filename=None,
            signer=None,
            console_mode="pretty"
    ):
        if hasattr(self, "logger"):
            self.logger.log(
                message=message,
                level=level,
                print_to_console=print_to_console,
                include_timestamp=include_timestamp,
                override_path=override_path,
                override_filename=override_filename,
                signer=signer,
                console_mode=console_mode
            )
        else:
            # fallback print if logger is missing
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [{level}] {message}")


        # 🔧 Build log entry
        log_entry = {
            "level": level,
            "message": message
        }

        if include_timestamp:
            log_entry["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

        if signer:
            try:
                payload = json.dumps(log_entry, sort_keys=True).encode()
                log_entry["sig"] = base64.b64encode(signer(payload)).decode()
            except Exception as e:
                print(f"[LOGGER][WARN] Signature failed: {e}")

        # 📄 Prepare output for disk (JSON always)
        output = json.dumps(log_entry, ensure_ascii=False)

        # 🔐 Encrypt if swarm key is active
        if hasattr(self, "_decoded_swarm_key"):
            output = self._encrypt_line(output)

        # 🖨 Console Output
        if print_to_console:
            if console_mode == "json" or hasattr(self, "_decoded_swarm_key"):
                print(output)
            else:
                ts = log_entry.get("timestamp", "")
                lvl = log_entry.get("level", "INFO")
                msg = log_entry.get("message", "")
                emoji = {
                    "INFO": "🔹",
                    "ERROR": "❌",
                    "WARNING": "⚠️",
                    "DEBUG": "🐞"
                }.get(lvl.upper(), "🔸")
                print(f"{emoji} [{ts}] [{lvl}] {msg}")

        # 📝 Write to log file (structured)
        path = (
            os.path.join(override_path, override_filename)
            if override_path and override_filename
            else self.default_log_file
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)

        try:
            with open(path, "a") as f:
                f.write(output.rstrip() + "\n")  # force newline, strip extras
        except Exception as e:
            print(f"[LOGGER][ERROR] Failed to write to {path}: {e}")

    def _encrypt_line(self, line: str) -> str:
        nonce = get_random_bytes(12)
        cipher = AES.new(self._decoded_swarm_key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(line.encode())
        blob = nonce + tag + ciphertext
        return base64.b64encode(blob).decode()

    @staticmethod
    def decrypt_log_line(line, key_bytes):
        try:
            blob = base64.b64decode(line.strip())
            nonce, tag, ciphertext = blob[:12], blob[12:28], blob[28:]
            cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag).decode()
        except Exception as e:
            return f"[DECRYPT-FAIL] {str(e)}"

    def set_encryption_key(self, swarm_key_b64):
        self._decoded_swarm_key = base64.b64decode(swarm_key_b64)

    @staticmethod
    def render_log_line(entry: dict) -> str:
        """
        Convert a JSON log entry into a flat CLI-style string.
        """
        ts = entry.get("timestamp", "")
        level = entry.get("level", "INFO")
        msg = entry.get("message", "")
        return f"[{ts}] [{level}] {msg}"