import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
import json
import subprocess
import time
from matrixswarm.core.boot_agent import BootAgent

class Agent(BootAgent):
    def __init__(self):
        super().__init__()

        self.inbox = os.path.join(self.path_resolution["comm_path"], self.command_line_args["universal_id"], "incoming")
        os.makedirs(self.inbox, exist_ok=True)
        self.log("[LINUX] Ready for scout missions.")

    def msg_check(self, content, packet):
        query_id = packet.get("query_id")
        tracer_session_id= packet.get("tracer_session_id", "blank")
        packet_id= packet.get("packet_id", -1)
        command = content.get("check")
        reflex_id = packet.get("reflex_id", "sgt-in-arms")

        if not query_id or not command:
            self.log("[SCOUT][SKIP] Missing 'check' or 'query_id'")
            return

        self.log(f"[SCOUT] Running check for query {query_id}: {command}")
        #this runs the command
        output, error = self.run_check(command)
        self.reply(query_id, tracer_session_id, packet_id, output or "", reflex_id, command, error)

    def save_local_report(self, report):
        report_dir = os.path.join(self.path_resolution["comm_path_resolved"], "reports")
        os.makedirs(report_dir, exist_ok=True)
        with open(os.path.join(report_dir, f"{report['report_id']}.json"), "w") as f:
            json.dump(report, f, indent=2)

    def run_check(self, command):
        try:
            output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=5)
            return output.decode("utf-8").strip(), None
        except subprocess.CalledProcessError as e:
            return "", e.output.decode("utf-8").strip()
        except Exception as e:
            return "", str(e)

    def report_back_to_oracle(mission_id, roundtrip, results):
        return json.dumps({
            "mission_id": mission_id,
            "roundtrip": roundtrip,
            "report": results
        }, indent=2)

    def reply(self, query_id, tracer_session_id, packet_id, message, reflex_id, command, error=None):

        report = {
            "type": "scan_cycle",
            "query_id": query_id,
            "tracer_session_id": tracer_session_id,
            "packet_id": packet_id,
            "report_id": f"scan_{int(time.time())}",
            "status": "failure" if error else "success",
            "command": command,
            "output": message if not error else None,
            "error": error,
            "ts": int(time.time())
        }

        reply_path = os.path.join(self.path_resolution["comm_path"], reflex_id, "incoming", f"{query_id}.msg")
        os.makedirs(os.path.dirname(reply_path), exist_ok=True)
        with open(reply_path, "w") as f:
            json.dump(report, f, indent=2)

        self.save_to_trace_session(report, msg_type="msg")

        self.log(f"[SCOUT] Sent report → {reflex_id}/{query_id}.msg")



if __name__ == "__main__":
    agent = Agent()
    agent.boot()