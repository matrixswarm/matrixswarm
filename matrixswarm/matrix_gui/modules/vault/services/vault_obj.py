import json, os

class VaultObj:
    def __init__(self, path=None, vault=None, password=None, encryptor=None, decryptor=None):
        self._path = path
        self._password = password
        self._encryptor = encryptor
        self._decryptor = decryptor
        self._vault = vault if vault is not None else self._load()
        self.connected = self._vault is not None
        self.error = None if self.connected else "Vault not loaded"

    def _load(self):
        if not self._path or not os.path.isfile(self._path):
            self.error = f"Vault file not found: {self._path}"
            return None
        with open(self._path, "rb") as f:
            data = f.read()
        if self._decryptor and self._password:
            data = self._decryptor(data, self._password)
        else:
            data = data.decode("utf-8")
        return json.loads(data)

    def get(self, key_path):
        parts = key_path.strip("/").split("/")
        obj = self._vault
        try:
            for k in parts:
                obj = obj[k]
            return obj
        except Exception as e:
            self.error = f"Not found: {key_path} ({e})"
            return None

    def save(self, key_path, value, persist=True):
        parts = key_path.strip("/").split("/")
        obj = self._vault
        for k in parts[:-1]:
            obj = obj.setdefault(k, {})
        obj[parts[-1]] = value
        if persist:
            self._persist()
        return True

    def delete(self, key_path, persist=True):
        parts = key_path.strip("/").split("/")
        obj = self._vault
        for k in parts[:-1]:
            obj = obj.get(k, {})
        obj.pop(parts[-1], None)
        if persist:
            self._persist()
        return True

    def _persist(self):
        if not self._path:
            raise Exception("No vault file path set.")
        data = json.dumps(self._vault, indent=2).encode("utf-8")
        if self._encryptor and self._password:
            data = self._encryptor(data, self._password)
        with open(self._path, "wb") as f:
            f.write(data)

    def as_dict(self):
        return self._vault

    def is_connected(self):
        return self.connected

    def reconnect(self):
        self._vault = self._load()
        self.connected = self._vault is not None
        return self

    def strip_secrets(self, keys_to_strip=("bot_token", "password", "creds", "key", "client_secret")):
        # Recursively strip keys in-place
        def _strip(obj):
            if isinstance(obj, dict):
                for k in list(obj.keys()):
                    if k in keys_to_strip:
                        obj[k] = "***"
                    else:
                        _strip(obj[k])
            elif isinstance(obj, list):
                for x in obj:
                    _strip(x)
        vcopy = json.loads(json.dumps(self._vault))  # Deep copy
        _strip(vcopy)
        return vcopy
