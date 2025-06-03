from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes, PrivateKeyTypes
class EncryptionConfig:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EncryptionConfig, cls).__new__(cls)

            cls._instance._enabled = False
            cls._instance._public_key = None
            cls._instance._private_key = None
            cls._instance._matrix_public_key = None
            cls._instance._matrix_private_key = None
            cls._instance._swarm_key = None

        return cls._instance

    def set_swarm_key(self, key: str):
        self._swarm_key = key

    def get_swarm_key(self):
        return self._swarm_key

    def set_public_key(self, key):
        self._public_key = key

    def get_public_key(self):
        return self._public_key

    def set_private_key(self, key):
        self._private_key = key

    def get_private_key(self):
        return self._private_key

    def set_matrix_public_key(self, key):
        self._matrix_public_key = key

    def get_matrix_public_key(self):
        return self._matrix_public_key

    def set_matrix_private_key(self, key):
        self._matrix_private_key = key

    def get_matrix_private_key(self):
        return self._matrix_private_key

    def set_enabled(self, enabled: bool=True):
        self._enabled=bool(enabled)

    def is_enabled(self) -> bool:
        return self._enabled

ENCRYPTION_CONFIG = EncryptionConfig()