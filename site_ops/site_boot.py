#!/usr/bin/env python3
"""
MatrixSwarm Launcher – Smart Boot

This tool:
- Boots the MatrixSwarm AI universe.
- Detects your current Python environment.
- Injects the correct Python interpreter and site-packages path.
- Allows manual override for edge cases or advanced users.

Run with:
  python site_boot.py --universe ai
  python site_boot.py --universe ai --python-site /custom/site-packages
  python site_boot.py --universe ai --python-bin /custom/bin/python3
"""

import os
import sys
import time
import argparse
import site
import hashlib
from pathlib import Path
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

# === ARGUMENTS ===
parser = argparse.ArgumentParser(description="MatrixSwarm Boot Loader", formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument("--universe", required=True, help="Target universe ID (e.g., ai, bb, os)")
parser.add_argument("--directive", default="default", help="Boot directive (e.g., matrix)")
parser.add_argument("--reboot", action="store_true", help="Soft reboot — skip hard cleanup")
parser.add_argument("--verbose", action="store_true", help="Enable verbose terminal output")
parser.add_argument("--python-site", help="Override Python site-packages path to inject")
parser.add_argument("--python-bin", help="Override Python interpreter to use for agent spawns")

args = parser.parse_args()

universe_id = args.universe.strip()
boot_name = args.directive.strip().replace(".py", "")
reboot = args.reboot
verbose = args.verbose

# === ENVIRONMENT DETECTION ===
python_exec = args.python_bin.strip() if args.python_bin else sys.executable

if args.python_site:
    python_site = args.python_site.strip()
else:
    try:
        python_site = next(p for p in site.getsitepackages() if "site-packages" in p and Path(p).exists())
    except Exception:
        python_site = "/root/miniconda3/lib/python3.12/site-packages"  # Fallback guess

print(f"🧠 Python Executable  : {python_exec}")
print(f"📦 Site-Packages Path : {python_site}")
if args.python_site:
    print(f"📌 [Override] --python-site = {args.python_site}")
if args.python_bin:
    print(f"📌 [Override] --python-bin  = {args.python_bin}")

# === PRE-BOOT GUARD ===
validate_universe_id(universe_id)
if not reboot:
    enforce_single_matrix_instance(universe_id)
os.environ["UNIVERSE_ID"] = universe_id

# === BOOT SESSION SETUP ===
SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SwarmSessionRoot.inject_boot_args(site_root=SITE_ROOT)

session = SwarmSessionRoot()
base_path = session.base_path
agent_source = os.path.join(SITE_ROOT, "agent")
pm = PathManager(root_path=base_path, agent_override=agent_source, site_root_path=SITE_ROOT)

# === POD & COMM ===
pod_path = pm.get_path("pod", trailing_slash=False)
comm_path = pm.get_path("comm", trailing_slash=False)
os.makedirs(pod_path, exist_ok=True)
os.makedirs(comm_path, exist_ok=True)

# === REBOOT? ===
if reboot:
    print("[REBOOT] 💣 Full MIRV deployment initiated.")
    Reaper(pod_root=pod_path, comm_root=comm_path).kill_universe_processes(universe_id)
    time.sleep(3)

# === LOAD TREE ===
print(f"[BOOT] Universe path resolved: {base_path}")
print(f"[BOOT] Loading directive: {boot_name}.py")
matrix_directive = load_boot_directive(boot_name)
tp = TreeParser.load_tree_direct(matrix_directive)
if not tp:
    print("[FATAL] Tree load failed. Invalid structure.")
    sys.exit(1)
if tp.rejected_subtrees:
    print(f"[RECOVERY] ⚠️ Removed duplicate nodes: {tp.rejected_subtrees}")

# === SPAWN CORE ===
MATRIX_UUID = matrix_directive.get("universal_id", "matrix")
matrix_without_children = {k: v for k, v in matrix_directive.items() if k != "children"}

cp = CoreSpawner(path_manager=pm, site_root_path=SITE_ROOT, python_site=python_site, detected_python=python_exec)
if verbose:
    cp.set_verbose(True)

# === Set up Matrix comm channel and trust ===
cp.ensure_comm_channel(MATRIX_UUID, [{
    'name': 'agent_tree_master.json',
    'type': 'f',
    'atomic': True,
    'content': tp.root
}], matrix_directive)

from core.mixin.ghost_vault import generate_agent_keypair
from cryptography.hazmat.primitives import serialization
import hashlib

# 🔐 Generate Matrix's keypair and fingerprint
matrix_keys = generate_agent_keypair()
matrix_pub_obj = serialization.load_pem_public_key(matrix_keys["pub"].encode())
fp = hashlib.sha256(matrix_keys["pub"].encode()).hexdigest()[:12]
print(f"[TRUST] Matrix pubkey fingerprint: {fp}")

# 🧠 Inject trust tree for internal spawn operations
cp._trust_tree = {
    "parent": matrix_pub_obj,
    "matrix": matrix_pub_obj
}

# 🧱 Inject Matrix's own secure_keys and identity into her directive
matrix_without_children["secure_keys"] = matrix_keys
matrix_without_children["parent_pub"] = matrix_keys["pub"]
matrix_without_children["matrix_pub"] = matrix_keys["pub"]

# 🚀 Create pod and deploy Matrix
new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
cp.spawn_agent(new_uuid, MATRIX_UUID, MATRIX_UUID, "site_boot", matrix_without_children, universe_id=universe_id)

print("[✅] Matrix deployed at:", pod_path)
print("[🔐] Matrix public key fingerprint:", fp)
print("[🧠] The swarm is online.")