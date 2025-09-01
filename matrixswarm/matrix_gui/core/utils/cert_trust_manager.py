# cert_trust_manager.py — Tactical handler for Python TLS trust enforcement
import ssl
import tempfile
from matrix_gui.core.utils.cert_loader import load_cert_chain_from_memory

class CertTrustManager:
    def __init__(self, *, ca_pem: str, cert_pem: str = None, key_pem: str = None):
        self.ca_pem = ca_pem
        self.cert_pem = cert_pem
        self.key_pem = key_pem

    def hardened_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED

        try:
            # Write CA cert to a temporary file — more reliable than cadata
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as f:
                f.write(self.ca_pem.encode())
                f.flush()
                ctx.load_verify_locations(cafile=f.name)
        except Exception as e:
            raise RuntimeError(f"[TLS] Failed to load CA cert via cafile: {e}")

        if self.cert_pem and self.key_pem:
            try:
                load_cert_chain_from_memory(ctx, self.cert_pem, self.key_pem)
            except Exception as e:
                raise RuntimeError(f"[TLS] Failed to load client cert/key: {e}")

        return ctx
