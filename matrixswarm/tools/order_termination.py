import os
import json
import time

def send_termination(universal_id, comm_root="/sites/orbit/python/comm"):
    """ Send a 'die' command to a specific agent by universal_id. """
    target_dir = os.path.join(comm_root, universal_id, "incoming")
    if not os.path.isdir(target_dir):
        print(f"[ERROR] Comm path not found for {universal_id}: {target_dir}")
        return

    filename = f"kill_{int(time.time())}.cmd"
    full_path = os.path.join(target_dir, filename)

    command = {
        "action": "die",
        "target": universal_id,
        "reason": "order_66"
    }

    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(command, f, indent=2)

    print(f"[ORDER-66] Execution order for {universal_id} issued → {full_path}")

# Example:
if __name__ == "__main__":
    agents = [
        "matrix",
        "watchdog-1",
        "watchdog-2",
        "worker-backup-1",
        "worker-backup-2",
        "courier-1",
        "logger-1",
        "logger-2",
        "logger-3",
        "logger-4",
        # Add others as needed
    ]

    for agent in agents:
        send_termination(agent)