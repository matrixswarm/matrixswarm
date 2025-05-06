import os
import time

def last_heartbeat_delta(comm_root, agent_id):
    try:
        path = os.path.join(comm_root, agent_id, "hello.moto", "last.ping")
        if not os.path.exists(path):
            return None
        return time.time() - os.path.getmtime(path)
    except Exception:
        return None