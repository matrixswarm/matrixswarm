import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core")))
from core import CoreAgent

class comm(CoreAgent):
    def __init__(self):
        super().__init__(agent_name="worker", force_random_uuid=True)
        print(f"[WORKER] Agent online with UUID: {self.uuid}")
        print(f"[WORKER] Parent UUID: {self.parent_uuid}")
        self.run_main_loop(duration=60)

if __name__ == "__main__":
    comm()