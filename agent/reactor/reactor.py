import os
import json
import time

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent

class ReactorAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.payload_dir = os.path.join(self.path_resolution["comm_path_resolved"], "payload")
        os.makedirs(self.payload_dir, exist_ok=True)
        self.spawn_target = os.path.join(self.path_resolution["comm_path"], "matrix", "payload")
        os.makedirs(self.spawn_target, exist_ok=True)

    def pre_boot(self):
        message = "ReactorAgent online. Listening for Oracle directives."
        print(message)
        self.broadcast(message)

    def post_boot(self):
        message = "Reactor standing by for dynamic agent deployment."
        print(message)
        self.broadcast(message)

    def broadcast(self, message):
        try:
            mailman_dir = os.path.join(self.path_resolution["comm_path"], "mailman-1", "payload")
            os.makedirs(mailman_dir, exist_ok=True)
            payload = {
                "uuid": self.command_line_args.get("permanent_id", "reactor-1"),
                "timestamp": time.time(),
                "severity": "info",
                "msg": message
            }
            fname = f"reactor_boot_{int(time.time())}.json"
            with open(os.path.join(mailman_dir, fname), "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            self.log(f"[REACTOR][ERROR] {e}")

    def worker(self):
        self.log("[REACTOR] Agent online. Monitoring for Oracle decisions...")
        while self.running:
            try:
                for fname in os.listdir(self.payload_dir):
                    if not fname.endswith(".json"):
                        continue
                    fpath = os.path.join(self.payload_dir, fname)
                    with open(fpath, "r") as f:
                        msg = json.load(f)

                    action = msg.get("action_taken")
                    classification = msg.get("classification")

                    if classification == "threat" and action == "interrupted":
                        self.deploy_defense_agent("mirror-2", "filesystem_mirror")

                    os.remove(fpath)
            except Exception as e:
                self.log(f"[REACTOR][ERROR] {e}")
            time.sleep(2)

    def deploy_defense_agent(self, perm_id, agent_name):
        spawn_payload = {
            "command": "spawn_agent",
            "payload": {
                "perm_id": perm_id,
                "agent_name": agent_name,
                "directives": {
                    "watch_path": "/etc",
                    "mode": "snapshot"
                }
            }
        }
        fname = f"reactor_spawn_{int(time.time())}.json"
        path = os.path.join(self.spawn_target, fname)
        with open(path, "w") as f:
            json.dump(spawn_payload, f, indent=2)
        self.log(f"[REACTOR] Dispatched spawn request for {agent_name} as {perm_id}.")

if __name__ == "__main__":
    # label = None
    # if "--label" in sys.argv:
    #   label = sys.argv[sys.argv.index("--label") + 1]

    # current directory of the agent script or it wont be able to find itself
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))

    reactor = ReactorAgent(path_resolution, command_line_args)

    reactor.boot()
