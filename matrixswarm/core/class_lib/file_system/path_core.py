import os
import time
from datetime import datetime

class SwarmSessionRoot:
    """
    Creates per-reboot epoch directories for a universe.
    Example:
        /matrix/ai/20250917_175950/{comm,pod}
    Also maintains symlink:
        /matrix/ai/latest -> /matrix/ai/<reboot_uuid>
    """
    def __init__(self, universe_id="default", reboot_uuid=None, base="/matrix"):
        self.universe_id = universe_id
        self.reboot_uuid = reboot_uuid or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base_universe = os.path.join(base, universe_id)
        self.root_path = os.path.join(self.base_universe, self.reboot_uuid)

        self.comm_path = os.path.join(self.root_path, "comm")
        self.pod_path = os.path.join(self.root_path, "pod")

        # Ensure directories
        for d in [self.base_universe, self.root_path, self.comm_path, self.pod_path]:
            os.makedirs(d, exist_ok=True)

        # Maintain "latest" symlink
        self._set_latest_symlink()

    def _set_latest_symlink(self):
        latest = os.path.join(self.base_universe, "latest")
        try:
            if os.path.islink(latest) or os.path.exists(latest):
                os.remove(latest)
            os.symlink(self.root_path, latest)
        except OSError as e:
            print(f"[WARN][SESSION] Failed to update latest symlink: {e}")


class PathManager:
    """
    Wraps SwarmSessionRoot with static paths, exposes path_resolution
    used by CoreSpawner, BootAgent, ghost_vault, etc.
    """

    def __init__(self, universe_id="default", reboot_uuid=None,
                 base="/matrix", python_exec="python3"):

        # Boot a new swarm session
        self.session = SwarmSessionRoot(universe_id=universe_id,
                                        reboot_uuid=reboot_uuid,
                                        base=base)

        self.base_static = os.path.join(base, "static")

        # Static dirs
        self.static_paths = {
            "agents": os.path.join(self.base_static, "agents"),
            "universes": os.path.join(self.base_static, "universes"),
            "comm": os.path.join(self.base_static, "comm", universe_id),
        }

        # Runtime dirs
        self.runtime_paths = {
            "comm": self.session.comm_path,
            "pod": self.session.pod_path,
        }

        # Ensure static dirs exist
        for p in self.static_paths.values():
            os.makedirs(p, exist_ok=True)

        self.python_exec = python_exec

    def build_resolution(self, universal_id, spawn_uuid):
        """
        Build the path_resolution dict injected into the vault.
        """
        return {
            # Root + universes
            "root_path": self.session.root_path,
            "universe_id": self.session.universe_id,
            "reboot_uuid": self.session.reboot_uuid,

            # Runtime comm (tmpfs/epoch-scoped)
            "comm_path": self.runtime_paths["comm"],
            "comm_path_resolved": os.path.join(self.runtime_paths["comm"], universal_id),

            # Static comm (disk, persistent)
            "comm_static_path_resolved": os.path.join(self.static_paths["comm"], universal_id),

            # Logs (always static)
            "log_path_resolved": os.path.join(self.static_paths["comm"], universal_id, "logs", "agent.log"),

            # Pods (runtime)
            "pod_path": self.runtime_paths["pod"],
            "pod_path_resolved": os.path.join(self.runtime_paths["pod"], spawn_uuid),

            # Agents (static binaries/scripts)
            "agent_path": self.static_paths["agents"],

            # Legacy/compat keys
            "incoming_path_template": os.path.join(self.runtime_paths["comm"], "$universal_id", "incoming"),
            "poke_worker_file": os.path.join(self.runtime_paths["comm"], universal_id,
                                             "hello.moto", "poke.worker"),
            "site_root_path": self.base_static,
            "install_path": self.base_static,
            "python_site": self.base_static,
            "python_exec": self.python_exec,
        }
