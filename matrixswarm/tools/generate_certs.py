import os
import sys
import subprocess
import stat
import shutil

workspace = os.path.expanduser("~/.matrixswarm")
local_script = os.path.join(workspace, "generate_certs.sh")

# Copy from package tools folder if not already there
if not os.path.exists(local_script):
    pkg_script = os.path.join(os.path.dirname(__file__), "generate_certs.sh")
    shutil.copy2(pkg_script, local_script)
    os.chmod(local_script, 0o755)
    print(f"[GENCERTS] ✅ Copied script to {local_script}")

def main():
    script_path = os.path.join(os.path.dirname(__file__), "generate_certs.sh")
    args = sys.argv[1:]

    if not os.path.exists(script_path):
        print(f"❌ Script not found at {script_path}")
        sys.exit(1)

    if not os.access(script_path, os.X_OK):
        try:
            os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC)
            print(f"[GENCERTS] 🛠 Set executable flag on {script_path}")
        except Exception as e:
            print(f"[GENCERTS] ⚠️ Failed to set executable, falling back to 'bash': {e}")
            subprocess.run(['bash', script_path] + args, check=True)
            return

    try:
        subprocess.run([script_path] + args, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[GENCERTS] ❌ Script exited with code {e.returncode}")
        print(f"[GENCERTS] ❗ Command: {e.cmd}")
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()