from uuid import uuid4
from datetime import datetime

def make_reaper_node(targets, perm_ids, mission_name=None):
    """
    Build a DisposableReaperAgent tree node with an embedded kill list and perm_ids.
    """
    uid = uuid4().hex[:6]
    kill_id = mission_name or f"reaper-strike-{uid}"

    node = {
        "permanent_id": kill_id,
        "name": "reaper",
        "filesystem": {
            "folders": []
        },
        "config": {
            "kill_list": targets,
            "perm_ids": perm_ids,  # <<<< THIS IS THE BIG ADD
            "created": datetime.now().strftime("%Y%m%d%H%M%S")
        }
    }

    return node