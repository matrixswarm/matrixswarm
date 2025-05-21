
# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

import subprocess
import os
import time
import json
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep
from datetime import datetime


class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)
        self.name = "RedisHammer"
        cfg = self.tree_node.get("config", {})
        self.interval = cfg.get("check_interval_sec", 10)
        self.service_name = cfg.get("service_name", "redis")
        self.redis_port = cfg.get("redis_port", 6379)
        self.socket_path = cfg.get("socket_path", "/var/run/redis/redis-server.sock")
        self.restart_limit = cfg.get("restart_limit", 3)
        self.always_alert = bool(cfg.get("always_alert", 1))
        self.failed_restarts = 0
        self.disabled = False
        self.alerts = {}
        self.alert_cooldown = 600
        self.last_status = None
        self.stats = {
            "date": self.today(),
            "uptime_sec": 0,
            "downtime_sec": 0,
            "restarts": 0,
            "last_state": None,
            "last_change": time.time()
        }

    def today(self):
        return datetime.now().strftime("%Y-%m-%d")

    def is_redis_running(self):
        try:
            result = subprocess.run(["systemctl", "is-active", "--quiet", self.service_name], check=False)
            return result.returncode == 0
        except Exception as e:
            self.log(f"[HAMMER][ERROR] systemctl failed: {e}")
            return False

    def is_port_open(self):
        try:
            out = subprocess.check_output(["ss", "-ltn"])
            return f":{self.redis_port}".encode() in out
        except Exception:
            return False

    def is_socket_up(self):
        return os.path.exists(self.socket_path)

    def restart_redis(self):
        if self.disabled:
            self.log("[HAMMER] Watchdog disabled. Restart skipped.")
            return
        try:
            subprocess.run(["systemctl", "restart", self.service_name], check=True)
            self.log("[HAMMER] ✅ Redis successfully restarted.")
            self.failed_restarts = 0
            self.stats["restarts"] += 1
        except Exception as e:
            self.failed_restarts += 1
            self.log(f"[HAMMER][FAIL] Restart failed: {e}")
            if self.failed_restarts >= self.restart_limit:
                self.disabled = True
                self.alert_operator("redis-failout", "💀 Redis hammer disabled after repeated restart failures.")

    def update_stats(self, running):
        now = time.time()
        elapsed = now - self.stats["last_change"]
        if self.stats["last_state"] is not None:
            if self.stats["last_state"]:
                self.stats["uptime_sec"] += elapsed
            else:
                self.stats["downtime_sec"] += elapsed
        self.stats["last_state"] = running
        self.stats["last_change"] = now

    def should_alert(self, key):

        if self.always_alert:
            return True

        now = time.time()
        last = self.alerts.get(key, 0)
        if now - last > self.alert_cooldown:
            self.alerts[key] = now
            return True
        return False

    def alert_operator(self, qid, message=None):

        if message:
            msg = f"{message}"
        else:
            msg = f"🚨 REDIS REFLEX TERMINATION\n\nReflex loop failed (exit_code = -1)"

        comms = self.get_nodes_by_role('comm')
        if not comms:
            self.log("[REFLEX][ALERT] No comm nodes found. Alert not dispatched.")
        else:
            for comm in comms:
                self.log(f"[REFLEX] Alert routed to comm agent: {comm['universal_id']}")
                self.drop_reflex_alert(msg, comm['universal_id'], level="critical", cause="[PARSE ERROR]")

    def drop_reflex_alert(self, message, agent_dir, level="critical", cause=""):
        """
        Drop a reflex alert .msg file into /incoming/<agent_dir>/ for comm relays to pick up.
        Respects factory-injected Discord/Telegram agents already listening.
        """

        msg_body = message if message else "[REFLEX] No message provided."
        formatted_msg = f"📣 Swarm Message\n{msg_body}"
        payload = {
            "type": "send_packet_incoming",
            "content": {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": self.command_line_args.get("universal_id", "unknown"),
                "level": level,
                "msg": msg_body,
                "formatted_msg": formatted_msg,
                "cause": cause or msg_body,
                "origin": self.command_line_args.get("universal_id", "unknown")
            }
        }
        try:
            inbox = os.path.join(self.path_resolution["comm_path"], agent_dir, "incoming")
            os.makedirs(inbox, exist_ok=True)
            path = os.path.join(inbox, f"redis_alert_{int(time.time())}.msg")
            with open(path, "w") as f:
                json.dump(payload, f)
        except Exception as e:
            self.log(f"[HAMMER][ALERT][FAIL] Could not drop alert: {e}")

    def persist_log(self):
        dir = os.path.join(self.path_resolution["comm_path"], "redis-hammer")
        os.makedirs(dir, exist_ok=True)
        path = os.path.join(dir, f"uptime_{self.stats['date']}.log")
        with open(path, "w") as f:
            json.dump(self.stats, f, indent=2)
        self.log(f"[HAMMER] 📊 Daily log written: {path}")

    def maybe_roll_day(self):
        if self.stats["date"] != self.today():
            self.persist_log()
            self.stats = {
                "date": self.today(),
                "uptime_sec": 0,
                "downtime_sec": 0,
                "restarts": 0,
                "last_state": None,
                "last_change": time.time()
            }

    def worker(self):
        self.maybe_roll_day()
        running = self.is_redis_running()
        accessible = self.is_port_open() or self.is_socket_up()
        last_state = self.stats["last_state"]  # snapshot before update
        self.update_stats(running)

        # ✅ Recovery alert logic
        if running:
            if last_state is False:  # just transitioned from down
                if self.should_alert("redis-recovered"):
                    self.alert_operator("redis-recovered", "✅ Redis has recovered and is now online.")

            if not accessible:
                self.alert_operator("redis-unreachable", "⚠️ Redis is active but unreachable via port or socket.")
            self.log("[HAMMER] ✅ Redis is running.")

        else:
            if self.should_alert("redis-down"):
                self.alert_operator("redis-down", "❌ Redis is DOWN. Attempting restart.")
            self.log("[HAMMER] ❌ Redis is NOT running. Restarting.")
            self.restart_redis()

        interruptible_sleep(self, self.interval)


if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
