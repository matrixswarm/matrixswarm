from matrix_gui.modules.vault.crypto.cert_factory import (_generate_root_ca, _generate_signed_cert, spki_pin_from_pem)
from cryptography import x509
from datetime import datetime
import uuid

def resolve(agent, vcs, deployment_record):
    tag = agent["name"]
    ca_cert_pem, ca_key_pem, ca_key_obj = _generate_root_ca(f"{tag}_ca")
    issuer_cert = x509.load_pem_x509_certificate(ca_cert_pem.encode())

    server_cert_pem, server_key_pem, _ = _generate_signed_cert(
        common_name=f"{tag}_server",
        sans=[],
        issuer_cert=issuer_cert,
        issuer_key=ca_key_obj
    )
    client_cert_pem, client_key_pem, _ = _generate_signed_cert(
        common_name=f"{tag}_client",
        sans=[],
        issuer_cert=issuer_cert,
        issuer_key=ca_key_obj
    )

    bundle = {
        "server": {"cert": server_cert_pem, "key": server_key_pem,
                   "spki_pin": spki_pin_from_pem(server_cert_pem)},
        "client": {"cert": client_cert_pem, "key": client_key_pem,
                   "spki_pin": spki_pin_from_pem(client_cert_pem)},
        "ca": {"cert": ca_cert_pem, "key": ca_key_pem},
        "created_at": datetime.utcnow().isoformat() + "Z",
        "path": f"/matrix/certs/{uuid.uuid4().hex[:8]}"
    }

    # persist to vault deployment section
    #dep_store = vcs.get_store("deployments")
    #dep_id = deployment_record["deployment_id"]
    #dep_store.set_nested(dep_id, ["certs", agent["name"]], bundle)
    return bundle
