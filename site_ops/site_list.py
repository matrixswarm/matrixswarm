import psutil
import os
import sys
import argparse

SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SITE_ROOT not in sys.path:
    sys.path.insert(0, SITE_ROOT)


def get_active_boot_ids():
    boot_ids = set()
    for proc in psutil.process_iter(['cmdline']):
        try:
            cmd = proc.info['cmdline']
            if not cmd:
                continue
            for part in cmd:
                if "/pod/" in part and "/matrix/" in part:
                    # Break full path into parts
                    parts = part.split("/")
                    if "matrix" in parts:
                        idx = parts.index("matrix")
                        if len(parts) > idx + 2:
                            boot_id = parts[idx + 2]
                            if boot_id != "latest":
                                boot_ids.add(boot_id)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return boot_ids

print("==================================================")
print("          MATRIX UNIVERSE SCANNER + STATUS")
print("==================================================")

matrix_root = "/matrix"

parser = argparse.ArgumentParser(description="List universes and active boots")
parser.add_argument("--universe", help="Only show a specific universe")
args = parser.parse_args()

universes = []

if args.universe:
    path = os.path.join(matrix_root, args.universe)
    if os.path.isdir(path):
        universes.append(args.universe)
    else:
        print(f"[ERROR] Universe '{args.universe}' does not exist.")
        exit(1)
else:
    if not os.path.isdir(matrix_root):
        print(f"[ERROR] Matrix root directory not found: {matrix_root}")
        exit(1)
    universes = [d for d in os.listdir(matrix_root) if os.path.isdir(os.path.join(matrix_root, d))]

if not universes:
    print("[INFO] No universes found.")
    exit(0)

active_boots = get_active_boot_ids()

for universe in universes:
    base = os.path.join(matrix_root, universe)
    print(f"🌌 Universe: {universe}")
    latest = os.path.join(base, "latest")
    if os.path.islink(latest):
        print(f" └── latest → {os.readlink(latest)}")

    boots = sorted(
        [b for b in os.listdir(base) if b != "latest"],
        reverse=True
    )
    for boot in boots:
        status = "🔥" if boot in active_boots else "❄️"
        print(f"     ├── Boot: {boot} {status}")
    print()
