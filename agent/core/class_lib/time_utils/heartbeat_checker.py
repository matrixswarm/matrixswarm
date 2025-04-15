import os
import time

def last_heartbeat_delta(comm_path, agent_id):
    hello_path = os.path.join(comm_path, agent_id, "hello.moto")
    if not os.path.isdir(hello_path):
        return None  # no hello.moto folder

    try:
        latest = max(
            (os.path.getmtime(os.path.join(hello_path, f)) for f in os.listdir(hello_path)),
            default=0
        )
        return time.time() - latest
    except Exception:
        return None