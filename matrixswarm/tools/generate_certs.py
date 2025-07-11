from pathlib import Path
import subprocess
import sys
import os
# Manually fix sys.path if needed
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from matrixswarm.core.utils.pointer_utils import get_swarm_root

def main():
    try:
        swarm_root = get_swarm_root()
        local_script = swarm_root / "generate_certs.sh"

        if not local_script.exists():
            print(f"[GENCERTS] ❌ generate_certs.sh not found in workspace: {local_script}")
            sys.exit(1)

        # Execute script
        os.chmod(local_script, 0o755)
        print(f"[GENCERTS] 🛠 Executing: {local_script}")
        subprocess.run([str(local_script)] + sys.argv[1:], check=True)

    except Exception as e:
        print(f"[GENCERTS] ❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()