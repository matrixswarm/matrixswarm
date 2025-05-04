
import os
import sys
import argparse

SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SITE_ROOT not in sys.path:
    sys.path.insert(0, SITE_ROOT)

from agent.core.class_lib.processes.reaper import Reaper
from agent.core.path_manager import PathManager

# CLI setup
parser = argparse.ArgumentParser(description="Matrix Swarm Terminator")
parser.add_argument("--universe", required=True, help="Target universe ID to wipe")
args = parser.parse_args()

universe_id = args.universe.strip()
base_path = os.path.join("/matrix", universe_id, "latest")



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

# Validate pod path
if not os.path.exists(pod_path):
    print(f"[ERROR] Pod path does not exist: {pod_path}")
    print(f"[INFO] Re-checking using ps aux | grep '{universe_id}' for live boot.")
    exit(1)


# Confirm paths exist
if not os.path.exists(pod_path):
    print(f"[ERROR] Pod path does not exist: {pod_path}")
    sys.exit(1)

if not os.path.exists(comm_path):
    print(f"[ERROR] Comm path does not exist: {comm_path}")
    sys.exit(1)

# Reap all
print("[REAPER] Engaging swarm-wide kill...")
reaper = Reaper(pod_root=pod_path, comm_root=comm_path)
reaper.reap_all()

# Remove folders
print("[WIPE] Nuking directories...")
os.system(f"rm -rf {pod_path}")
os.system(f"rm -rf {comm_path}")

print(f"[☠️ ] Matrix '{universe_id}' has been terminated.")
