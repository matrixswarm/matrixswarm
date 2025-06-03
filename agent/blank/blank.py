import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.name = "BlankAgent"

    def pre_boot(self):
        self.log("[BLANK] Pre-boot checks complete.")

    def post_boot(self):
        self.log("[BLANK] Post-boot ready. Standing by.")

    def worker(self, config:dict = None):
        self.log("[BLANK] Worker loop alive.")
        print("Guess what time it is?")
        interruptible_sleep(self, 10)

if __name__ == "__main__":
    agent = Agent()
    agent.boot()