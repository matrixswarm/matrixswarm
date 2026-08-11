import os, base64, uuid
from datetime import datetime

def resolve(agent, vcs, deployment_record):
    key = base64.b64encode(os.urandom(32)).decode()
    payload = {
        "key": key,
        "type": "aes",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "path": f"/matrix/crypto/{uuid.uuid4().hex[:8]}"
    }
    dep_store = vcs.get_store("deployments")
    dep_id = deployment_record["deployment_id"]
    dep_store.set_nested(dep_id, ["symmetric", agent["name"]], payload)
    return payload
