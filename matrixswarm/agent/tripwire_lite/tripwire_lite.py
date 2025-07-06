import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import time
import inotify.adapters
from datetime import datetime
from matrixswarm.core.boot_agent import BootAgent
from matrixswarm.core.utils.swarm_sleep import interruptible_sleep
from matrixswarm.core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.name = "TripwireLite"

        cfg = self.tree_node.get("config", {})
        self.watch_paths = cfg.get("watch_paths", [
            "agent", "core", "boot_directives", "matrix_gui", "https_certs", "socket_certs"
        ])

        self.abs_watch_paths = [
            os.path.join(self.path_resolution["site_root_path"], path) for path in self.watch_paths
        ]
        self.cooldown = 60
        self.last_seen = {}

    def log_event(self, event_type, full_path):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if time.time() - self.last_seen.get(full_path, 0) < self.cooldown:
            return  # suppress spam
        self.last_seen[full_path] = time.time()

        msg = (
            f"🧪 Tripwire Event\n"
            f"• Path: {full_path}\n"
            f"• Event: {event_type}\n"
            f"• Time: {timestamp}"
        )
        self.log(f"[TRIPWIRE] {msg}")
        # self.alert_operator(message=msg)  # optional alert to Discord/etc.

    def worker(self, config:dict = None, identity:IdentityObject = None):
        i = inotify.adapters.Inotify()
        for path in self.abs_watch_paths:
            if os.path.exists(path):
                i.add_watch(path, mask=inotify.constants.IN_MODIFY | inotify.constants.IN_CREATE | inotify.constants.IN_DELETE)
                self.log(f"[TRIPWIRE] Watching {path}")
            else:
                self.log(f"[TRIPWIRE][SKIP] Missing: {path}")

        for event in i.event_gen(yield_nones=False):
            (_, type_names, path, filename) = event
            full_path = os.path.join(path, filename)
            self.log_event(", ".join(type_names), full_path)

        interruptible_sleep(self, 10)

if __name__ == "__main__":
    agent = Agent()
    agent.boot()
