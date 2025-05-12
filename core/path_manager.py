import os
from core.swarm_session_root import SwarmSessionRoot

class PathManager:
    def __init__(self, root_path=None, use_session_root=False, agent_override=None, site_root_path=None):
        self.paths = {}

        if use_session_root:
            session = SwarmSessionRoot()
            self.set_from_session(session)
            self.session = session
            self.paths["session_path"] = session.base_path
            self.paths["session_boot_payload"] = os.path.join(session.base_path, "boot_payload")
        else:
            # Resolve one level up from this file
            self.root_path = root_path or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            self.paths["root"] = self.root_path
            self.add_path("comm", "comm")
            self.add_path("pod", "pod")
            self.add_path("agent", "agent")

        # Inject override if provided
        if agent_override:
            self.paths["agent"] = agent_override
        else:
            self.add_path("agent", "agent")

        if site_root_path:
            self.paths["site_root_path"] = site_root_path
            self.paths["agent"] = os.path.join(site_root_path, "agent")

    def set_from_session(self, session):
        self.paths = {
            "root": session.root_path,
            "comm": session.comm_path,
            "pod": session.pod_path,
            "agent": session.agent_path
        }
        self.root_path = session.root_path

    def get_all_paths(self):
        return self.paths

    def _ensure_root(self, path):
        return path if os.path.isabs(path) else os.path.abspath(os.path.join(self.root_path, path))

    def add_path(self, key, path):
        self.paths[key] = self._ensure_root(path)

    def add_paths(self, paths):
        if not isinstance(paths, dict):
            raise ValueError("Expected a dictionary for paths.")
        for key, path in paths.items():
            if not isinstance(key, str) or not isinstance(path, str):
                raise ValueError("Keys and values in the paths dictionary must be strings.")
            self.add_path(key, path)

    def get_path(self, key, trailing_slash=True):
        path = self.paths.get(key)
        if path and trailing_slash and not path.endswith(os.sep):
            path += os.sep
        return path

    def construct_path(self, *segments, trailing_slash=True):
        if not all(isinstance(segment, str) for segment in segments):
            raise ValueError("All path segments must be strings.")
        full_path = os.path.join(self.root_path, *segments)
        if trailing_slash and not full_path.endswith(os.sep):
            full_path += os.sep
        return full_path

    def list_paths(self):
        return self.paths
