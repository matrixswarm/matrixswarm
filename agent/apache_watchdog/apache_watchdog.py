
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
        self.name = "ApacheSentinel"
        cfg = self.tree_node.get("config", {})
        self.interval = cfg.get("check_interval_sec", 10)
        self.service_name = cfg.get("service_name", "httpd")  # or "httpd" on RHEL
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

    def is_apache_running(self):
        try:
            result = subprocess.run(["systemctl", "is-active", "--quiet", self.service_name], check=False)
            return result.returncode == 0
        except Exception as e:
            self.log(f"[WATCHDOG][ERROR] systemctl failed: {e}")
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

    def restart_apache(self):
        if self.disabled:
            self.log("[WATCHDOG] Watchdog disabled. Restart skipped.")
            return
        try:
            subprocess.run(["systemctl", "restart", self.service_name], check=True)
            self.log("[WATCHDOG] ✅ Apache successfully restarted.")
            self.failed_restarts = 0
            self.stats["restarts"] += 1
        except Exception as e:
            self.failed_restarts += 1
            self.log(f"[WATCHDOG][FAIL] Restart failed: {e}")
            if self.failed_restarts >= self.restart_limit:
                self.disabled = True
                self.alert_operator("💀 Apache Watchdog disabled after repeated restart failures.")

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
        pk = self.get_delivery_packet("notify.alert.general", new=True)
        pk.set_data({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "universal_id": self.command_line_args.get("universal_id", "unknown"),
            "level": "critical",
            "msg": message,
            "formatted_msg": f"📣 Apache Watchdog\n{message}",
            "cause": "Apache Sentinel Alert",
            "origin": self.command_line_args.get("universal_id", "unknown")
        })
        comms = self.get_nodes_by_role("comm")
        if not comms:
            self.log("[WATCHDOG][ALERT] No comm nodes found. Alert not dispatched.")
            return
        for comm in comms:
            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
              .set_address([comm["universal_id"]]) \
              .set_drop_zone({"drop": "incoming"}) \
              .set_packet(pk) \
              .deliver()

            if da.get_error_success() != 0:
                self.log(f"[ALERT][FAIL] {comm['universal_id']}: {da.get_error_success_msg()}")
            else:
                self.log(f"[ALERT] Delivered to {comm['universal_id']}")

    def persist_log(self):
        dir = os.path.join(self.path_resolution["comm_path"], "apache-sentinel")
        os.makedirs(dir, exist_ok=True)
        path = os.path.join(dir, f"uptime_{self.stats['date']}.log")
        with open(path, "w") as f:
            json.dump(self.stats, f, indent=2)
        self.log(f"[WATCHDOG] 📊 Daily log written: {path}")

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
        running = self.is_apache_running()
        ports_open = self.are_ports_open()
        last_state = self.stats["last_state"]
        self.update_stats(running)

        if running and ports_open:
            if last_state is False:
                self.alert_operator("✅ Apache has recovered and is now online.")
            self.log("[WATCHDOG] ✅ Apache is running.")
        else:
            if self.should_alert("apache-down"):
                self.alert_operator("❌ Apache is DOWN or not binding required ports.")
            self.log("[WATCHDOG] ❌ Apache is NOT healthy. Restarting.")
            self.restart_apache()

        interruptible_sleep(self, self.interval)

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()