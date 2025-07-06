import os
import sys
import subprocess

REQUIRED_PACKAGES = [
    "requests",
    "beautifulsoup4",
    "lxml",
    "websockets",
    "psutil",
    "soupsieve",
    "inotify_simple",
    "certifi"
]

def install_package(pkg):
    try:
        print(f"[BOOTSTRAP] Installing: {pkg}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", pkg])
    except subprocess.CalledProcessError:
        print(f"[ERROR] Failed to install: {pkg}")

def main():
    print("🧠 Swarm Bootstrap — Package Installer for MatrixSwarm Agents")
    print("==============================================\n")

    # Optional: create venv
    # subprocess.run([sys.executable, "-m", "venv", "logai-env"])

    for pkg in REQUIRED_PACKAGES:
        install_package(pkg)

    print("\n✅ All required packages installed.")
    print("You’re now ready to launch the swarm.\n")

if __name__ == "__main__":
    main()
