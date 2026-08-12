import os
import ipaddress
import base64, hashlib
from cryptography.x509 import KeyUsage
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from datetime import datetime, timedelta
from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.common.crypto.interfaces.cert_consumer import CertConsumer
from matrix_gui.modules.common.crypto.interfaces.signing_cert_consumer import SigningCertConsumer
from matrix_gui.modules.common.crypto.interfaces.symmetric_encryption_consumer import SymmetricEncryptionConsumer
from cryptography.x509 import SubjectAlternativeName, DNSName, IPAddress
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

def spki_pin_from_pem(cert_pem: str) -> str:
    cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")

def _generate_keypair():
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    privkey_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()
    pubkey_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return privkey_pem, pubkey_pem, key

def _generate_self_signed_cert(key, common_name, sans=None):
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name)
    ])
    builder = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)\
        .public_key(key.public_key())\
        .serial_number(x509.random_serial_number())\
        .not_valid_before(datetime.utcnow())\
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))\
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)\
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    if sans:
        san_objs = []
        for san in sans:
            try:
                san_objs.append(IPAddress(ipaddress.ip_address(san)))
            except ValueError:
                san_objs.append(DNSName(san))
        builder = builder.add_extension(SubjectAlternativeName(san_objs), critical=False)
    cert = builder.sign(key, algorithm=hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _generate_root_ca(common_name: str, key_size: int = 4096):
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name)
    ])

    builder = x509.CertificateBuilder()\
        .subject_name(subject)\
        .issuer_name(issuer)\
        .public_key(key.public_key())\
        .serial_number(x509.random_serial_number())\
        .not_valid_before(datetime.utcnow())\
        .not_valid_after(datetime.utcnow() + timedelta(days=3650)) \
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True) \
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False) \
        .add_extension(KeyUsage(
        digital_signature=False,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=True,
        crl_sign=True,
        encipher_only=False,
        decipher_only=False
    ), critical=True)

    cert = builder.sign(private_key=key, algorithm=hashes.SHA256())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()

    return cert_pem, priv_pem, key


def _generate_signed_cert(common_name: str, sans: list, issuer_cert, issuer_key, key_size: int = 2048):
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size
    )

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name)
    ])

    builder = x509.CertificateBuilder()\
        .subject_name(subject)\
        .issuer_name(issuer_cert.subject)\
        .public_key(key.public_key())\
        .serial_number(x509.random_serial_number())\
        .not_valid_before(datetime.utcnow())\
        .not_valid_after(datetime.utcnow() + timedelta(days=3650)) \
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True) \
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False) \
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False) \
        .add_extension(KeyUsage(
        digital_signature=True,
        content_commitment=False,
        key_encipherment=True,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=False,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False
    ), critical=True) \
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                       critical=False)

    if sans:
        san_objs = []
        for san in sans:
            try:
                san_objs.append(IPAddress(ipaddress.ip_address(san)))
            except ValueError:
                san_objs.append(DNSName(san))
        builder = builder.add_extension(SubjectAlternativeName(san_objs), critical=False)

    cert = builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()

    return cert_pem, priv_pem, key



# Patch: Minimalist `connection_ca_root` for HTTPS and WebSocket agents
# This patch updates `connection_cert_factory()` to ONLY emit `cert` field in connection_ca_root
# when preparing the vault cert bundle for agents.

def connection_cert_factory(wrapped_agents):
    if not isinstance(wrapped_agents, list):
        return

    for wrapper in wrapped_agents:
        try:
            if not isinstance(wrapper, CertConsumer):
                continue
            if not wrapper.requires_cert():
                continue

            tag = wrapper.get_cert_tag()
            sans = wrapper.get_sans() if wrapper.use_sans() else {}

            # === Step 1: Generate a single Root CA
            ca_cert_pem, ca_key_pem, ca_key_obj = _generate_root_ca(f"{tag}_ca")
            issuer_cert = x509.load_pem_x509_certificate(ca_cert_pem.encode("utf-8"))

            # === Step 2: Generate a dedicated Server Certificate signed by the CA
            server_cert_pem, server_key_pem, _ = _generate_signed_cert(
                common_name=f"{tag}_server",
                sans=sans.get("ip", []) + sans.get("dns", []),
                issuer_cert=issuer_cert,
                issuer_key=ca_key_obj
            )

            # === Step 3: Generate a dedicated Client Certificate signed by the CA
            client_cert_pem, client_key_pem, _ = _generate_signed_cert(
                common_name=f"{tag}_client",
                sans=sans.get("ip", []) + sans.get("dns", []),
                issuer_cert=issuer_cert,
                issuer_key=ca_key_obj
            )

            # === Step 4: Consolidate all certificates into a single dictionary
            server_spki = spki_pin_from_pem(server_cert_pem)
            client_spki = spki_pin_from_pem(client_cert_pem)

            consolidated_certs = {
                "server_cert": {
                    "cert": server_cert_pem,
                    "key": server_key_pem,
                    "spki_pin": server_spki,
                },
                "client_cert": {
                    "cert": client_cert_pem,
                    "key": client_key_pem,
                    "spki_pin": client_spki,
                },
                "ca_root": {
                    "cert": ca_cert_pem,
                    "key": ca_key_pem,
                }
            }

            # === Step 5: Inject the consolidated certificates into the agent
            wrapper.set_cert(consolidated_certs)

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.connection_cert_factory", e)


def signing_cert_factory(wrapped_agents):
    if not isinstance(wrapped_agents, list):
        return

    for wrapper in wrapped_agents:
        try:
            if not isinstance(wrapper, SigningCertConsumer):
                continue

            # Must support signing certs
            if not wrapper.requires_signing():
                continue

            key_priv, key_pub, _ = _generate_keypair()
            remote_privkey, remote_pubkey, _ = _generate_keypair()
            signing_profile = {
                "pubkey": key_pub,
                "privkey": key_priv, #gui will sign packets with this
                "remote_pubkey": remote_pubkey,
                "remote_privkey": remote_privkey, #remote server will sign packets with this
                "created_at": datetime.utcnow().isoformat() + "Z",
                #"serial": wrapper.get_serial()
            }

            wrapper.set_signing_cert(signing_profile)

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.signing_factory", e)

def symmetric_encryption_factory(wrapped_agents):
    if not isinstance(wrapped_agents, list):
        return


    for wrapper in wrapped_agents:
        try:

            if not isinstance(wrapper, SymmetricEncryptionConsumer):
                continue

            # Must support signing certs
            if not wrapper.requires_symmetric_encryption():
                continue

            # Make a random AES key (32 bytes = 256-bit)
            aes_key = os.urandom(32)
            aes_key_b64 = base64.b64encode(aes_key).decode()

            symmetric_profile = {
                "key": aes_key_b64,
                "type": "aes",
                "created_at": datetime.utcnow().isoformat() + "Z"
            }

            wrapper.set_symmetric_key(symmetric_profile)

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.symmetric_encryption_factory", e)



def initialize():
    # Register listener at import time
    EventBus.on("crypto.service.connection_cert.injector", connection_cert_factory)
    EventBus.on("crypto.service.signing_cert.injector", signing_cert_factory)
    EventBus.on("crypto.service.symmetric_encryption.injector", symmetric_encryption_factory)
    print("[SWARM] Receiver online. Listening for crypto.factory.connection_cert...")