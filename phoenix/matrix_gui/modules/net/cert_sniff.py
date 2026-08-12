# cert_sniff.py
import ssl, socket, hashlib, base64
from typing import Optional
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes

def _read_server_cert(sock) -> bytes:
    pem = ssl.DER_cert_to_PEM_cert(sock.getpeercert(True))
    return pem.encode("utf-8")

def _extract_cn(pem_bytes: bytes) -> Optional[str]:
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        cert = x509.load_pem_x509_certificate(pem_bytes, default_backend())
        for attr in cert.subject:
            # OID 2.5.4.3 = CN
            if getattr(attr, "oid", None) and getattr(attr.oid, "dotted_string", "") == "2.5.4.3":
                return attr.value
    except Exception:
        return None
    return None

def get_server_cert_info_direct(host: str, port: int, timeout: float = 2.0):
    """Plain TCP → TLS → read cert, no client cert required."""
    raw = socket.create_connection((host, port), timeout=timeout)
    try:
        ctx = ssl.create_default_context()
        # We don't care about validation here, only reading the presented cert
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        tls = ctx.wrap_socket(raw, server_hostname=host)
        try:
            pem = _read_server_cert(tls)
        finally:
            tls.close()
    finally:
        raw.close()
    sha256 = hashlib.sha256(pem).hexdigest()
    cn = _extract_cn(pem)
    return {"pem": pem.decode("utf-8"), "sha256": sha256, "cn": cn}

def get_server_cert_info_via_http_proxy(proxy_host: str, proxy_port: int, host: str, port: int, timeout: float = 3.0):
    """HTTP CONNECT tunnel → TLS → cert. SOCKS not supported here."""
    raw = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        connect_req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
        raw.sendall(connect_req.encode("ascii"))
        resp = raw.recv(4096)
        if b" 200 " not in resp.split(b"\r\n", 1)[0]:
            raise OSError(f"HTTP CONNECT failed: {resp.splitlines()[0]!r}")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        tls = ctx.wrap_socket(raw, server_hostname=host)
        try:
            pem = _read_server_cert(tls)
        finally:
            tls.close()
    finally:
        raw.close()
    sha256 = hashlib.sha256(pem).hexdigest()
    cn = _extract_cn(pem)
    return {"pem": pem.decode("utf-8"), "sha256": sha256, "cn": cn}

def spki_b64_from_pem(pem_str: str) -> str:
    cert = x509.load_pem_x509_certificate(pem_str.encode("utf-8"))
    spki_der = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )

    return base64.b64encode(spki_der).decode("ascii")