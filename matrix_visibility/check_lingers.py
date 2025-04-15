import os

POD_DIR = "/sites/orbit/python/pod"
COMM_DIR = "/sites/orbit/python/comm"


def list_dirs(path):
    return set(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))


def check_lingers():
    print("\n👻 GHOST SCAN INITIATED\n========================")

    pods = list_dirs(POD_DIR) if os.path.exists(POD_DIR) else set()
    comms = list_dirs(COMM_DIR) if os.path.exists(COMM_DIR) else set()

    # Ghost pods: have runtime but no communication
    ghost_pods = pods - comms
    for uuid in ghost_pods:
        print(f"[ORPHAN POD] /pod/{uuid} has no /comm entry")

    # Ghost comms: have communication setup but no pod alive
    ghost_comms = comms - pods
    for perm_id in ghost_comms:
        print(f"[STALE COMM] /comm/{perm_id} has no matching /pod agent")

    # Missing or empty hello.moto check
    for perm_id in comms:
        moto_path = os.path.join(COMM_DIR, perm_id, "hello.moto")
        if not os.path.exists(moto_path):
            print(f"[MISSING] hello.moto for {perm_id} is absent")
        elif not os.listdir(moto_path):
            print(f"[DEAD] hello.moto for {perm_id} is empty — agent silent")

    print("\n👁️ Ghost scan complete. Review above for anomalies.\n")


if __name__ == "__main__":
    check_lingers()
