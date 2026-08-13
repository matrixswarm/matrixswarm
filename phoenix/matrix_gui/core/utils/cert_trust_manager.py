# cert_trust_manager.py — Tactical handler for Python TLS trust enforcement
import ssl
from matrix_gui.core.utils.cert_loader import load_cert_chain_from_memory

class CertTrustManager:
    def __init__(self, *, ca_pem: str, cert_pem: str = None, key_pem: str = None):
        self.ca_pem = ca_pem
        self.cert_pem = cert_pem
        self.key_pem = key_pem

    def hardened_ssl_context(self) -> ssl.SSLContext:
        if not self.ca_pem:
            raise ValueError("A CA root is required for TLS server verification")

        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

        try:
            ctx.load_verify_locations(cadata=self.ca_pem)
        except Exception as e:
            raise RuntimeError(f"[TLS] Failed to load CA cert: {e}")

        if self.cert_pem and self.key_pem:
            try:
                load_cert_chain_from_memory(ctx, self.cert_pem, self.key_pem)
            except Exception as e:
                raise RuntimeError(f"[TLS] Failed to load client cert/key: {e}")

        return ctx