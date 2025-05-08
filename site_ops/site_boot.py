import os
import sys
import argparse
import psutil

# Path prep
SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SITE_ROOT not in sys.path:
    sys.path.insert(0, SITE_ROOT)
# CLI parsing FIRST
parser = argparse.ArgumentParser(description="Matrix Swarm Launcher")
parser.add_argument("--universe", required=True, help="Target universe ID")
parser.add_argument("--directive", default="default", help="Boot directive (without .py)")
args = parser.parse_args()




import argparse
from agent.core.core_spawner import CoreSpawner
from agent.core.tree_parser import TreeParser
from agent.core.class_lib.processes.reaper import Reaper
from agent.core.path_manager import PathManager
from agent.core.swarm_session_root import SwarmSessionRoot

universe_id = args.universe.strip()
boot_name = args.directive.strip().replace(".py", "")

# Inject UNIVERSE_ID into environment for SwarmSessionRoot
os.environ["UNIVERSE_ID"] = universe_id
session = SwarmSessionRoot()
base_path = session.base_path



# Add site root to sys.path
SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SITE_ROOT not in sys.path:
    sys.path.insert(0, SITE_ROOT)

from boot_directives.load_boot_directive import load_boot_directive

# CLI flags
parser = argparse.ArgumentParser(description="Matrix Swarm Launcher")
parser.add_argument("--universe", required=True, help="Target universe ID")
parser.add_argument("--directive", default="default", help="Boot directive (without .py)")
args = parser.parse_args()

universe_id = args.universe.strip()
boot_name = args.directive.strip().replace(".py", "")

# Prevent duplicate Matrix spawns for the same universe
existing = psutil.process_iter(["cmdline"])
dupe_label = f"{universe_id}:site_boot:matrix:matrix"

# Prevent multiple instances of the same universe, still can happen but it will self rectify
for proc in existing:
    cmdline = " ".join(proc.info.get("cmdline") or [])
    if dupe_label in cmdline:
        print(f"[BLOCKED] Matrix already running in '{universe_id}'. Skipping boot.")
        exit(1)

# Base deploy target
base_path = os.path.join("/matrix", universe_id, "latest")
print(f"[BOOT] Universe path resolved: {base_path}")
print(f"[BOOT] Loading directive: {boot_name}.py")

# Load directive dynamically
matrix_directive = load_boot_directive(boot_name)

# Link real codebase
agent_source = os.path.join(SITE_ROOT, "agent")

# Prep paths
pm = PathManager(root_path=base_path, agent_override=agent_source)
pod_path = pm.get_path("pod", trailing_slash=False)
comm_path = pm.get_path("comm", trailing_slash=False)

os.makedirs(pod_path, exist_ok=True)
os.makedirs(comm_path, exist_ok=True)

# Clean field
print("[REAPER] Sweeping the old world clean...")
reaper = Reaper(pod_root=pod_path, comm_root=comm_path)
reaper.reap_all()

# Bootloader reset
cp = CoreSpawner(path_manager=pm)
cp.reset_hard()

# Load and validate tree fully before saving
tp = TreeParser.load_tree_direct(matrix_directive)

if not tp:
    print("[FATAL] Tree load failed. Invalid structure.")
    exit(1)

if tp.rejected_subtrees:
    print(f"[RECOVERY] ⚠️ Removed duplicate nodes: {tp.rejected_subtrees}")

comm_file_spec = [
    {
        'name': 'agent_tree_master.json',
        'type': 'f',
        'atomic': True,
        'content': tp.root
    },
]

MATRIX_UUID = matrix_directive.get("universal_id", "matrix")
matrix_without_children = {k: v for k, v in matrix_directive.items() if k != "children"}


cp.ensure_comm_channel(MATRIX_UUID, comm_file_spec, matrix_directive)
new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
cp.spawn_agent(new_uuid, MATRIX_UUID, MATRIX_UUID, "site_boot", matrix_without_children, universe_id=universe_id)

print(f"[✅] Matrix deployed at: {pod_path}")
print("[🧠] The swarm is online.")
