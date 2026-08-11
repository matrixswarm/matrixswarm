import os
from matrixswarm.core.swarm_session_root import SwarmSessionRoot

class PathManager:
    def __init__(self, universe_id="default", reboot_uuid=None, python_exec="python3"):
        # Boot a new swarm session
        self.session = SwarmSessionRoot(universe_id=universe_id, reboot_uuid=reboot_uuid)

        # Base roots
        self.base_static = "/matrix/static"
        self.base_universe = os.path.join("/matrix", universe_id, self.session.reboot_uuid)

        # Static dirs
        self.static_paths = {
            "agents": os.path.join(self.base_static, "agents"),
            "universes": os.path.join(self.base_static, "universes"),
            "comm": os.path.join(self.base_static, "comm", universe_id),
        }

        # Runtime dirs (from SessionRoot)
        self.runtime_paths = {
            "comm": self.session.comm_path,
            "pod": self.session.pod_path,
        }

        # Ensure static dirs exist
        for p in self.static_paths.values():
            os.makedirs(p, exist_ok=True)

        self.python_exec = python_exec

    def build_resolution(self, universal_id, spawn_uuid):
        return {
            "root_path": self.session.root_path,
            "pod_path": self.runtime_paths["pod"],
            "comm_path": self.runtime_paths["comm"],
            "agent_path": self.static_paths["agents"],

            # Runtime comm (tmpfs)
            "comm_runtime_path_resolved": os.path.join(self.runtime_paths["comm"], universal_id),

            # Static comm (disk)
            "comm_static_path_resolved": os.path.join(self.static_paths["comm"], universal_id),

            # Logs always → static
            "log_path_resolved": os.path.join(self.static_paths["comm"], universal_id, "logs", "agent.log"),

            # Pods
            "pod_path_resolved": os.path.join(self.runtime_paths["pod"], spawn_uuid),

            # Legacy for compatibility
            "incoming_path_template": os.path.join(self.runtime_paths["comm"], "$universal_id", "incoming"),
            "poke_worker_file": os.path.join(self.runtime_paths["comm"], universal_id, "hello.moto", "poke.worker"),

            "site_root_path": self.base_static,
            "install_path": self.base_static,
            "python_site": self.base_static,
            "python_exec": self.python_exec,
            "universe_id": self.session.universe_id,
            "reboot_uuid": self.session.reboot_uuid,
        }

