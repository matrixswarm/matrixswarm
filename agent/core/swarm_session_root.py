import os
import uuid
from datetime import datetime
from agent.core.class_lib.logging.logger import Logger



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

        self.root_path = os.environ.get("SWARM_ROOT", "/sites/orbit/python")
        self.base_path = os.path.join("/matrix", self.universe_id, self.reboot_uuid)
        self.comm_path = os.path.join(self.base_path, "comm")
        self.pod_path = os.path.join(self.base_path, "pod")
        self.agent_path = os.environ.get("AGENT_PATH", os.path.join(self.root_path, "agent"))

        os.makedirs(self.comm_path, exist_ok=True)
        os.makedirs(self.pod_path, exist_ok=True)

        self.set_latest_symlink()

        self.logger = Logger(os.path.join(self.comm_path, "logs"))
        self.logger.log(f"[SESSION] UNIVERSE_ID={self.universe_id} REBOOT_UUID={self.reboot_uuid}")

    def set_latest_symlink(self):
        latest_path = os.path.join("/matrix", self.universe_id, "latest")
        if os.path.islink(latest_path) or os.path.exists(latest_path):
            os.remove(latest_path)
        os.symlink(self.reboot_uuid, latest_path)

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
        if os.path.islink(latest_path) or os.path.isfile(latest_path):
            os.remove(latest_path)
        elif os.path.isdir(latest_path):
            os.rmdir(latest_path)  # 💥 Only removes if empty — safe fallback
        os.symlink(self.reboot_uuid, latest_path)

# Example usage:
if __name__ == "__main__":
    session = SwarmSessionRoot()
    paths = session.get_paths()
    print(paths["logger"])  # Confirm logger object is set
    print("\nSwarm session initialized.")
