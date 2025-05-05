import os
import json
import time
from agent.core.boot_agent import BootAgent
from agent.core.utils.swarm_sleep import interruptible_sleep

class LoggerSnipperAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.orbits = {}

    def worker_pre(self):
        self.log("[LOGGER SNIPPER] Booted and ready for timestamp duty.")

    def worker(self):
        def worker(self):
            now = time.strftime("%Y-%m-%d %H:%M:%S")  # ✅ Define now
            self.log(f"[LOGGER-SNIPPER] Log cycle at {now}")
            interruptible_sleep(self, 10)
    def worker_post(self):
        self.log("[LOGGER-SNIPPER] LoggerAgent is shutting down.")



if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = LoggerSnipperAgent(path_resolution, command_line_args)
    agent.boot()