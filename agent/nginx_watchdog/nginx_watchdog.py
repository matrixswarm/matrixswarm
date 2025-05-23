
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
        self.name = "NginxSentinel"
        cfg = self.tree_node.get("config", {})
        self.interval = cfg.get("check_interval_sec", 10)
        self.service_name = cfg.get("service_name", "nginx")
        self.ports = cfg.get("ports", [80, 443])
        self.restart_limit = cfg.get("restart_limit", 3)
        self.failed_restarts = 0
        self.disabled = False
        self.alerts = {}
        self.always_alert = bool(cfg.get("always_alert", 1))
        self.alert_cooldown = cfg.get("alert_cooldown", 300)
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

    def is_nginx_running(self):
        try:
            result = subprocess.run(["systemctl", "is-active", "--quiet", self.service_name], check=False)
            return result.returncode == 0
        except Exception as e:
            self.log(f"[SENTINEL][ERROR] systemctl failed: {e}")
            return False

    def are_ports_open(self):
        try:
            out = subprocess.check_output(["ss", "-ltn"])
            for port in self.ports:
                if f":{port}".encode() not in out:
                    return False
            return True
        except Exception:
            return False

    def restart_nginx(self):
        if self.disabled:
            self.log("[SENTINEL] Watchdog disabled. Restart skipped.")
            return
        try:
            subprocess.run(["systemctl", "restart", self.service_name], check=True)
            self.log("[SENTINEL] ✅ Nginx successfully restarted.")
            self.failed_restarts = 0
            self.stats["restarts"] += 1
        except Exception as e:
            self.failed_restarts += 1
            self.log(f"[SENTINEL][FAIL] Restart failed: {e}")
            if self.failed_restarts >= self.restart_limit:
                self.disabled = True
                self.alert_operator("💀 Nginx sentinel disabled after repeated restart failures.")

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

    def alert_operator(self, message=None):
        """
        Uses packet + delivery agent system to send alert to all comms.
        """
        if not message:
            message = "🚨 NGINX REFLEX TERMINATION\n\nReflex loop failed (exit_code = -1)"

        pk = self.get_delivery_packet("notify.alert.general", new=True)
        pk.set_data({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": self.command_line_args.get("universal_id", "unknown"),
                "level": "critical",
                "msg": message,
                "formatted_msg": f"📣 Swarm Message\n{message}",
                "cause": "Nginx Sentinel Alert",
                "origin": self.command_line_args.get("universal_id", "unknown")
        })

        comms = self.get_nodes_by_role("comm")
        if not comms:
            self.log("[ALERT] No comm nodes found. Alert not dispatched.")
            return

        for comm in comms:
            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
                .set_address([comm["universal_id"]]) \
                .set_drop_zone({"drop": "incoming"}) \
                .set_packet(pk) \
                .deliver()

            if da.get_error_success() != 0:
                self.log(f"[ALERT][DELIVERY-FAIL] {comm['universal_id']}: {da.get_error_success_msg()}")
            else:
                self.log(f"[ALERT][DELIVERED] Alert sent to {comm['universal_id']}")

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
        dir = os.path.join(self.path_resolution["comm_path"], "nginx-sentinel")
        os.makedirs(dir, exist_ok=True)
        path = os.path.join(dir, f"uptime_{self.stats['date']}.log")
        with open(path, "w") as f:
            json.dump(self.stats, f, indent=2)
        self.log(f"[SENTINEL] 📊 Daily log written: {path}")

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
        running = self.is_nginx_running()
        ports_open = self.are_ports_open()
        last_state = self.stats["last_state"]
        self.update_stats(running)

        if running and ports_open:
            if last_state is False:
                self.alert_operator("✅ Nginx has recovered and is now online.")
            self.log("[SENTINEL] ✅ Nginx is running.")
        else:
            if self.should_alert("nginx-down"):
                self.alert_operator("❌ Nginx is DOWN or not binding required ports.")
            self.log("[SENTINEL] ❌ Nginx is NOT healthy. Restarting.")
            self.restart_nginx()

        interruptible_sleep(self, self.interval)

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
