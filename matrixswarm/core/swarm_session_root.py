import os
import re
from datetime import datetime
from matrixswarm.core.class_lib.logging.logger import Logger



class SwarmSessionRoot:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SwarmSessionRoot, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return  # prevent re-init
        self._initialized = True

        self.universe_id = os.environ.get("UNIVERSE_ID", "bb")
        self.reboot_uuid = os.environ.get("REBOOT_UUID", datetime.now().strftime("%Y%m%d_%H%M%S"))

        # Lock the UUID globally
        os.environ["REBOOT_UUID"] = self.reboot_uuid


        #fallback root of site
        self.root_path = os.environ.get(
            "SWARM_ROOT",
            self._injected_args.get("site_root", "/sites/sites_root_path")
        )

        self.base_path = os.path.join("/matrix", self.universe_id, self.reboot_uuid)
        self.boot_payload_path = os.path.join(self.base_path, "boot_payload")
        self.comm_path = os.path.join(self.base_path, "comm")
        self.pod_path = os.path.join(self.base_path, "pod")
        self.agent_path = os.environ.get("AGENT_PATH", os.path.join(self.root_path, "agent"))

        os.makedirs(self.comm_path, exist_ok=True)
        os.makedirs(self.pod_path, exist_ok=True)

        self.set_latest_symlink()

        self.logger = Logger(os.path.join(self.comm_path, "logs"))
        self.logger.log(f"[SESSION] UNIVERSE_ID={self.universe_id} REBOOT_UUID={self.reboot_uuid}")

    _injected_args = {}

    @classmethod
    def inject_boot_args(cls, **kwargs):
        cls._injected_args.update(kwargs)

    def get_paths(self):
        return {
            "universe_id": self.universe_id,
            "reboot_uuid": self.reboot_uuid,
            "comm_path": self.comm_path,
            "pod_path": self.pod_path,
            "agent_path": self.agent_path,
            "root_path": self.root_path,
            "logger": self.logger
        }

    def set_latest_symlink(self):
        latest_path = os.path.join("/matrix", self.universe_id, "latest")

        try:
            # Handle all possible existing conditions
            if os.path.islink(latest_path) or os.path.isfile(latest_path):
                os.remove(latest_path)
            elif os.path.isdir(latest_path):
                os.rmdir(latest_path)  # Only works if it's empty
        except Exception as e:
            print(f"[SESSION][LINK] Warning: failed to clean up old latest symlink: {e}")

        try:
            os.symlink(self.reboot_uuid, latest_path)
            print(f"[SESSION] Set latest symlink: {latest_path} → {self.reboot_uuid}")
        except Exception as e:
            print(f"[SESSION][LINK][ERROR] Failed to create latest symlink: {e}")

# Example usage:
if __name__ == "__main__":
    session = SwarmSessionRoot()
    paths = session.get_paths()
    print(paths["logger"])  # Confirm logger object is set
    print("\nSwarm session initialized.")



def resolve_latest_symlink(universe):
    matrix_root = os.path.join("/matrix", universe)
    latest_path = os.path.join(matrix_root, "latest")

    # If symlink exists and is valid
    if os.path.islink(latest_path) and os.path.exists(os.readlink(latest_path)):
        print(f"[LATEST] Valid symlink already in place: {latest_path}")
        return True

    print(f"[LATEST] Missing or broken symlink. Attempting recovery...")

    try:
        # Find all reboot UUID folders
        boot_dirs = [
            d for d in os.listdir(matrix_root)
            if re.match(r"\d{8}_\d{6}", d) and os.path.isdir(os.path.join(matrix_root, d))
        ]

        if not boot_dirs:
            print("[LATEST][ERROR] No valid reboot folders found.")
            return False

        # Sort by datetime
        boot_dirs.sort(reverse=True)
        newest = boot_dirs[0]

        # Repair the symlink
        new_target = os.path.join(matrix_root, newest)

        if os.path.exists(latest_path) or os.path.islink(latest_path):
            os.remove(latest_path)

        os.symlink(newest, latest_path)
        print(f"[LATEST] Symlink repaired: {latest_path} → {newest}")
        return True

    except Exception as e:
        print(f"[LATEST][ERROR] Failed to repair symlink: {e}")
        return False