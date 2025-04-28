from uuid import uuid4
from datetime import datetime

def make_scavenger_node(mission_name=None):
    """
    Build a DisposableReaperAgent tree node with an embedded kill list.
    """
    uid = uuid4().hex[:6]
    kill_id = mission_name or f"scavenger-strike-{uid}"

    node = {
        "permanent_id": kill_id,
        "name": "scavenger",
        "filesystem": {
            "folders": []
        },
        "config": {
            "created": datetime.now().strftime("%Y%m%d%H%M%S")
        }
    }

    return node
