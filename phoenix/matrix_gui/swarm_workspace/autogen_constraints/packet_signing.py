from matrix_gui.modules.vault.crypto.cert_factory import _generate_keypair
import uuid

def resolve(agent, vcs, deployment_record):
    priv, pub, _ = _generate_keypair()
    remote_priv, remote_pub, _ = _generate_keypair()
    bundle = {
        "pubkey": pub,
        "privkey": priv,
        "remote_pubkey": remote_pub,
        "remote_privkey": remote_priv,
        "path": f"/matrix/signing/{uuid.uuid4().hex[:8]}"
    }

    dep_store = vcs.get_store("deployments")
    dep_id = deployment_record["deployment_id"]
    dep_store.set_nested(dep_id, ["signing", agent["name"]], bundle)
    return bundle
