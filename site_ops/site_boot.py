import os
import sys
import argparse
import time

verbose_mode=False

# Path prep
SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SITE_ROOT not in sys.path:
    sys.path.insert(0, SITE_ROOT)

from core.core_spawner import CoreSpawner
from core.tree_parser import TreeParser
from core.class_lib.processes.reaper import Reaper
from core.path_manager import PathManager
from core.swarm_session_root import SwarmSessionRoot
from boot_directives.load_boot_directive import load_boot_directive
from core.utils.boot_guard import enforce_single_matrix_instance, validate_universe_id

# Parse CLI args
parser = argparse.ArgumentParser(description="Matrix Swarm Launcher")
parser.add_argument("--universe", required=True, help="Target universe ID")
parser.add_argument("--directive", default="default", help="Boot directive (without .py)")
parser.add_argument("--reboot", action="store_true", help="Soft reboot — skip hard cleanup")
parser.add_argument("--verbose", action="store_true", help="Enable full terminal output")
args = parser.parse_args()

universe_id = args.universe.strip()
reboot = args.reboot
verbose = args.verbose
boot_name = args.directive.strip().replace(".py", "")

# Validate universe ID; Jet not legit
validate_universe_id(universe_id)

# Prevent double Matrix spawn unless --reboot
if not reboot:
    enforce_single_matrix_instance(universe_id)

# Inject universe ID into env for swarm components
os.environ["UNIVERSE_ID"] = universe_id

# Prepare pod/comm path from new session
SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
from core.swarm_session_root import SwarmSessionRoot
SwarmSessionRoot.inject_boot_args(site_root=SITE_ROOT)

# Create new boot session
session = SwarmSessionRoot()
base_path = session.base_path  # This is the timestamped path

agent_source = os.path.join(SITE_ROOT, "agent")
pm = PathManager(root_path=base_path, agent_override=agent_source, site_root_path=SITE_ROOT)
pod_path = pm.get_path("pod", trailing_slash=False)
comm_path = pm.get_path("comm", trailing_slash=False)

os.makedirs(pod_path, exist_ok=True)
os.makedirs(comm_path, exist_ok=True)

if reboot:
    print("[NUCLEAR REBOOT] 💣 No foreplay. No cookies. Full MIRV deployment.")
    reaper = Reaper(pod_root=pod_path, comm_root=comm_path)
    reaper.kill_universe_processes(universe_id)
    time.sleep(3)

# Load directive and spawn matrix
print(f"[BOOT] Universe path resolved: {base_path}")
print(f"[BOOT] Loading directive: {boot_name}.py")
matrix_directive = load_boot_directive(boot_name)


#Remove Any Duplicate Nodes In Json DIRECTIVE; Keep first contact nodes, removes subsequent
#duplicate node = sharing a universal_id
tp = TreeParser.load_tree_direct(matrix_directive)
if not tp:
    print("[FATAL] Tree load failed. Invalid structure.")
    sys.exit(1)
if tp.rejected_subtrees:
    print(f"[RECOVERY] ⚠️ Removed duplicate nodes: {tp.rejected_subtrees}")

# Write agent_tree_master.json to comm
comm_file_spec = [{
    'name': 'agent_tree_master.json',
    'type': 'f',
    'atomic': True,
    'content': tp.root
}]

MATRIX_UUID = matrix_directive.get("universal_id", "matrix")
matrix_without_children = {k: v for k, v in matrix_directive.items() if k != "children"}

cp = CoreSpawner(path_manager=pm, site_root_path=SITE_ROOT)
if verbose:
    cp.set_verbose(True)

cp.ensure_comm_channel(MATRIX_UUID, comm_file_spec, matrix_directive)
new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
cp.spawn_agent(new_uuid, MATRIX_UUID, MATRIX_UUID, "site_boot", matrix_without_children, universe_id=universe_id)

print(f"[✅] Matrix deployed at: {pod_path}")
print("[🧠] The swarm is online.")