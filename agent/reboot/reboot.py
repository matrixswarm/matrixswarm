import os
import time
from agent.core.boot_agent import BootAgent

class RebootAgent(BootAgent):
    def worker_pre(self):

        if shutdown_all:
            self.log("[REBOOT] Triggering swarm-wide kill via bootloader.")
            os.system("python3 bootloader.py --kill")
            self.log("[REBOOT] Waiting for swarm to terminate...")
            if not wait_for_swarm_shutdown():
                self.log("[REBOOT][WARNING] Some agents still detected after wait period.")

        self.log("[REBOOT] Agent engaged. Preparing full system reset.")

        config = tree_node.get("config", {}) if 'tree_node' in globals() else {}
        confirm = config.get("confirm", "NO")
        shutdown_all = config.get("shutdown_all", True)
        reboot_matrix = config.get("reboot_matrix", True)

        if confirm != "YES":
            self.log("[REBOOT][BLOCKED] Confirm flag not set to 'YES'. Aborting reboot.")
            self.running = False
            return

        if shutdown_all:
            self.log("[REBOOT] Triggering swarm-wide kill via bootloader.")
            os.system("python3 bootloader.py --kill")
            time.sleep(2)

        if reboot_matrix:
            self.log("[REBOOT] Relaunching Matrix.")
            os.system("python3 bootloader.py")

        self.log("[REBOOT] Self-termination complete.")
        self.running = False

    def worker(self):
        # Keep this light since pre handled everything
        time.sleep(2)

    def wait_for_swarm_shutdown(max_wait=20):
        for _ in range(max_wait):
            if not any("run" in p.name() and "--job" in " ".join(p.cmdline()) for p in psutil.process_iter()):
                return True
            time.sleep(1)
        return False

if __name__ == "__main__":
    path_resolution = {
        "pod_path_resolved": os.path.dirname(os.path.abspath(__file__)),
        "comm_path_resolved": "comm/reboot-1"
    }

    command_line_args = {
        "universal_id": "reboot-1",
        "agent_name": "reboot_agent",
        "install_name": "manual-reboot-call"
    }

    tree_node = {
        "config": {
            "confirm": "YES",
            "shutdown_all": True,
            "reboot_matrix": True
        }
    }

    agent = RebootAgent(path_resolution, command_line_args)
    agent.tree_node = tree_node
    agent.boot()
