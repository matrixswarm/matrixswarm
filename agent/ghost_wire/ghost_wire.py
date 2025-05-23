import os
import time
import json
import subprocess
from datetime import datetime
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep
from core.mixin.reflex_alert import ReflexAlertMixin

class Agent(BootAgent, ReflexAlertMixin):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)
        self.name = "GhostWire"
        self.sessions = {}
        self.command_patterns = ["rm -rf", "scp", "curl", "wget", "nano /etc","vi /etc", "vim /etc", "sudo", "su", "chmod 777"]
        self.session_dir = os.path.join(self.path_resolution["comm_path"], "shadow-tracker", "sessions")
        os.makedirs(self.session_dir, exist_ok=True)
        self.tick_rate = 5


    def worker_pre(self):
        self.log("[GHOSTWIRE] Shadow tracker engaged.")

    def worker(self):
        self.track_active_users()
        self.poll_shell_history()
        interruptible_sleep(self, self.tick_rate)

    def track_active_users(self):
        try:
            output = subprocess.check_output(["who"], text=True)
            for line in output.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    user, tty = parts[0], parts[1]
                    if user not in self.sessions:
                        self.sessions[user] = {
                            "tty": tty,
                            "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "commands": [],
                            "files_touched": [],
                            "last_seen": time.time()
                        }
                    else:
                        self.sessions[user]["last_seen"] = time.time()
        except Exception as e:
            self.log(f"[GHOSTWIRE][ERROR] Failed to track users: {e}")

    def poll_shell_history(self):
        for user, session in self.sessions.items():
            history_path = f"/home/{user}/.bash_history"
            if os.path.exists(history_path):
                try:
                    with open(history_path, "r") as f:
                        lines = f.read().splitlines()
                    new_commands = [cmd for cmd in lines if cmd not in session["commands"]]
                    for cmd in new_commands:
                        session["commands"].append(cmd)
                        self.log(f"[GHOSTWIRE][{user}] {cmd}")
                        if self.is_suspicious(cmd):
                            self.alert(user, cmd)
                    self.persist(user, session)
                except Exception as e:
                    self.log(f"[GHOSTWIRE][{user}][ERROR] {e}")

    def is_suspicious(self, cmd):
        return any(p in cmd for p in self.command_patterns)

    def alert(self, user, cmd):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        msg = (
            f"🕶️ Suspicious Command Detected\n"
            f"• User: {user}\n"
            f"• Command: {cmd}\n"
            f"• Time: {timestamp}"
        )

        self.log(f"[GHOSTWIRE][ALERT] {user}: {cmd}")
        self.alert_operator(message=msg)


    def persist(self, user, session):
        date_str = self.today()
        path = os.path.join(self.session_dir, user)
        os.makedirs(path, exist_ok=True)
        fpath = os.path.join(path, f"{date_str}.log")
        with open(fpath, "w") as f:
            json.dump(session, f, indent=2)

    def today(self):
        return datetime.now().strftime("%Y-%m-%d")

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
