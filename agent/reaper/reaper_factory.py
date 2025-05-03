from uuid import uuid4
from datetime import datetime

def make_reaper_node(targets, universal_ids, mission_name=None, tombstone_comm=True):
    from uuid import uuid4
    from datetime import datetime

    uid = uuid4().hex[:6]
    kill_id = mission_name or f"reaper-strike-{uid}"

    node = {
        "universal_id": kill_id,
        "name": "reaper",
        "filesystem": { "folders": [] },
        "config": {
            "kill_list": targets,
            "universal_ids": universal_ids,
            "tombstone_comm": tombstone_comm,
            "created": datetime.now().strftime("%Y%m%d%H%M%S")
        }
    }

    return node
