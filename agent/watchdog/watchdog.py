#Authored by Daniel F MacDonald and ChatGPT
# ╔════════════════════════════════════════════════════════╗
# ║                   🧠 WATCHDOG AGENT 🧠                ║
# ║   Central Cortex · Tree Dispatcher · Prime Director    ║
# ║     Forged in the core of Hive Zero | v3.0 Directive   ║
# ║   ║
# ╚════════════════════════════════════════════════════════╝
import sys
import os
import time
import requests
import json

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent

class WatchdogAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):

        super().__init__(path_resolution, command_line_args)


    def load_config(self):

        #injected through top of script during spawning
        config = tree_node.get("config", {}) if 'tree_node' in globals() else {}

        self.ping_url = config.get("ping_url", "https://matrixswarm.com")
        self.check_interval = config.get("check_interval_sec", 60)
        self.timeout = config.get("timeout_sec", 5)
        self.max_failures = config.get("max_failures", 3)
        self.alert_action = config.get("alert_action", "notify_matrix")

        self.log(
            f"[WATCHDOG][CONFIG] Loaded: ping={self.ping_url}, interval={self.check_interval}s, timeout={self.timeout}s, max_failures={self.max_failures}, action={self.alert_action}")

    def worker(self):


        self.load_config()
        self.log("[WATCHDOG] Config loaded in post_boot.")

        self.log("[WATCHDOG] WatchdogAgent is now running.")
        while self.running:
            try:
                response = requests.get(self.ping_url, timeout=self.timeout)
                if response.status_code != 200:
                    raise Exception(f"Bad status code: {response.status_code}")
                # Success, reset failure count
                self.failure_count = 0
                r = f"[WATCHDOG][INFO]Ping success: {self.ping_url} [200 OK]"
                self.log(r)
            except Exception as e:
                self.failure_count += 1
                r = f"[WATCHDOG][INFO]Ping failure: ({self.failure_count}/{self.max_failures}): {e}"
                self.log(r)
                if self.failure_count >= self.max_failures:
                    self.handle_alert(str(e))
                    self.failure_count = 0  # Reset after alert
            time.sleep(self.check_interval)

    def handle_alert(self, error_message):
        alert = {
            "cmd": "alert",
            "source": "watchdog",
            "issue": "matrixswarm.com unreachable",
            "details": {
                "url": self.ping_url,
                "error": error_message,
                "perm_id": self.command_line_args["permanent_id"],
                "uuid": self.command_line_args["install_name"],
                "timestamp": time.time()
            }
        }
        if self.alert_action == "notify_matrix":
            print(alert)
        elif self.alert_action == "log_only":
            r=f"[WATCHDOG][ALERT] (log_only): {json.dumps(alert)}"
            self.log(r)
        # Optional: add logic for direct replace/inject here

if __name__ == "__main__":
    # label = None
    # if "--label" in sys.argv:
    #   label = sys.argv[sys.argv.index("--label") + 1]

    # current directory of the agent script or it wont be able to find itself
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))

    agent = WatchdogAgent(path_resolution, command_line_args)

    agent.boot()
