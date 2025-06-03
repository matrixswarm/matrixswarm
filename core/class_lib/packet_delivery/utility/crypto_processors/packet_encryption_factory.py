from .encryptor import PacketEncryptor
from .decryptor import PacketDecryptor
from .plaintext_processor import PlaintextProcessor
from .plaintext_encryptor import PacketEncryptorPlaintext

def packet_encryption_factory(mode: str, key: bytes = None, priv_key=None, pub_key=None):
    """
    Creates a crypto processor based on mode.

    mode:
        - "encrypt" → returns PacketEncryptor (with optional signing)
        - "decrypt" → returns PacketDecryptor (with optional verification)
        - "plaintext" → returns PlaintextProcessor

    key:
        - Required for encrypt/decrypt

    priv_key: used to sign payloads during encryption
    pub_key: used to verify signatures during decryption
    """
    mode = mode.lower()

    if mode == "encrypt":
        if not key:
            raise ValueError("Encryption key required for 'encrypt' mode")
        return PacketEncryptor(key, priv_key=priv_key)

    elif mode == "decrypt":
        if not key:
            raise ValueError("Decryption key required for 'decrypt' mode")
        return PacketDecryptor(key, pub_key=pub_key)

    elif mode == "plaintext_encrypt":
        return PacketEncryptorPlaintext()

    elif mode == "plaintext":
        return PlaintextProcessor()

    else:
        raise ValueError(f"Unknown encryption mode: {mode}")