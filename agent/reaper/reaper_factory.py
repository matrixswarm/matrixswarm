from uuid import uuid4
from datetime import datetime
def make_reaper_node(targets, universal_ids, mission_name=None, tombstone_comm=True, tombstone_pod=True, delay=0, cleanup_die=False):

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
            "tombstone_pod": tombstone_pod,  # ✅ New
            "delay": delay,
            "cleanup_die": cleanup_die,
            "created": datetime.now().strftime("%Y%m%d%H%M%S")
        }
    }

    return node