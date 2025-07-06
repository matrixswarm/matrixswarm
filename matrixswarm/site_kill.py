
def main():
    import os
    import sys
    import argparse

    SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if SITE_ROOT not in sys.path:
        sys.path.insert(0, SITE_ROOT)

    from core.class_lib.processes.reaper import Reaper
    from core.path_manager import PathManager
    from core.utils import resolve_latest_symlink
    from core.utils import swarm_cleaner

    # CLI setup
    parser = argparse.ArgumentParser(description="Matrix Swarm Terminator")
    parser.add_argument("--universe", required=True, help="Target universe ID to wipe")
    parser.add_argument("--cleanup", action="store_true", help="Clean old boot directories after kill")
    args = parser.parse_args()

    universe_id = args.universe.strip()
    base_path = os.path.join("/matrix", universe_id, "latest")


    resolve_latest_symlink.resolve_latest_symlink(universe_id)
    latest_path = os.path.join("/matrix", universe_id, "latest")

    # Confirm
    print("==================================================")
    print("           MATRIX TERMINATION SEQUENCE")
    print("==================================================")
    print(f"[KILL] Target Universe: {universe_id}")
    print(f"[KILL] Base Path: {base_path}")

    # Get pod and comm paths
    pm = PathManager(root_path=base_path)
    pod_path = pm.get_path("pod", trailing_slash=False)
    comm_path = pm.get_path("comm", trailing_slash=False)

    if not os.path.exists(pod_path):
        print(f"[WARN] Pod path missing: {pod_path}. Reaper will skip pod scan.")

    if not os.path.exists(comm_path):
        print(f"[WARN] Comm path missing: {comm_path}. Some tombstones may fail.")

    print("[REAPER] Engaging swarm-wide kill...")
    reaper = Reaper(pod_root=pod_path, comm_root=comm_path)

    if os.path.exists(pod_path):
        reaper.reap_all()
    else:
        print(f"[REAPER][SKIP] Pod path missing: {pod_path}")

    print("[MEM-KILL] Double-checking memory for active --job matches...")
    reaper.kill_universe_processes(universe_id)

    if args.cleanup:
        print(f"[SWARM-CLEANER] Running post-kill cleanup for universe '{universe_id}'...")
        swarm_cleaner.clean_old_boots(universe_id=universe_id, keep_latest=1)
if __name__ == "__main__":
    main()
