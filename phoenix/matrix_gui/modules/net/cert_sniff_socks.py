# cert_sniff_socks.py
import socket, ssl, hashlib
from typing import Optional

def get_server_cert_info_via_socks5(proxy_host:str, proxy_port:int, host:str, port:int, user:str=None, password:str=None, timeout:float=6.0):
    s = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    s.settimeout(timeout)
    try:
        # Greeting
        if user:
            s.sendall(b"\x05\x02\x00\x02")  # VER=5, NMETHODS=2, METHODS=00(no auth),02(user/pass)
        else:
            s.sendall(b"\x05\x01\x00")      # VER=5, NMETHODS=1, METHODS=00(no auth)
        ver, method = s.recv(2)
        if ver != 5:
            raise OSError("SOCKS5 bad version")
        if method == 2:  # username/password
            u = (user or "").encode(); p = (password or "").encode()
            s.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            ver, status = s.recv(2)
            if status != 0:
                raise OSError("SOCKS5 auth failed")
        elif method != 0:
            raise OSError("SOCKS5 method not supported")

        # CONNECT
        # ATYP=3 (domain) or 1 (IPv4). We send domain.
        host_b = host.encode()
        req = b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + port.to_bytes(2, "big")
        s.sendall(req)
        rep = s.recv(4)
        if len(rep) < 4 or rep[1] != 0x00:
            raise OSError("SOCKS5 connect failed")
        # consume bind addr/port
        atyp = rep[3]
        if atyp == 1:  # IPv4
            s.recv(4); s.recv(2)
        elif atyp == 3:
            ln = s.recv(1)[0]; s.recv(ln); s.recv(2)
        elif atyp == 4:
            s.recv(16); s.recv(2)

        # TLS wrap
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        tls = ctx.wrap_socket(s, server_hostname=host)
        try:
            der = tls.getpeercert(True)
            pem = ssl.DER_cert_to_PEM_cert(der).encode()
        finally:
            tls.close()
    finally:
        s.close()

    # hash & CN
    sha256 = hashlib.sha256(pem).hexdigest()
    cn = None
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        cert = x509.load_pem_x509_certificate(pem, default_backend())
        for attr in cert.subject:
            if getattr(attr, "oid", None) and attr.oid.dotted_string == "2.5.4.3":
                cn = attr.value; break
    except Exception:
        pass
    return {"pem": pem.decode(), "sha256": sha256, "cn": cn}
