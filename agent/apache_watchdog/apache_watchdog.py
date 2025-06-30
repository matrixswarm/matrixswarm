
import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import subprocess
import time
import requests
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep
from datetime import datetime
from core.mixin.agent_summary_mixin import AgentSummaryMixin
from core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject

class Agent(BootAgent, AgentSummaryMixin):
    def __init__(self):
        super().__init__()
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
        # test writing summary
        #self.stats["date"] = "1900-01-01"

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
        if not message:
            message = "🚨 APACHE REFLEX TERMINATION\n\nReflex loop failed (exit_code = -1)"

        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({"handler": "cmd_send_alert_msg"})

        try:
            server_ip = requests.get("https://api.ipify.org").text.strip()
        except Exception:
            server_ip = "Unknown"

        pk2 = self.get_delivery_packet("notify.alert.general")
        pk2.set_data({
            "server_ip": server_ip,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "universal_id": self.command_line_args.get("universal_id", "unknown"),
            "level": "critical",
            "msg": message,
            "formatted_msg": f"📣 Apache Watchdog\n{message}",
            "cause": "Apache Sentinel Alert",
            "origin": self.command_line_args.get("universal_id", "unknown")
        })

        pk1.set_packet(pk2,"content")

        alert_nodes = self.get_nodes_by_role("hive.alert.send_alert_msg")
        if not alert_nodes:
            self.log("[WATCHDOG][ALERT] No alert-compatible agents found.")
            return

        for node in alert_nodes:
            football = self.get_football(type=self.FootballType.PASS)
            football.load_identity_file(universal_id=node["universal_id"])
            da = self.get_delivery_agent("file.json_file", football=football, new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
              .set_address([node["universal_id"]]) \
              .set_drop_zone({"drop": "incoming"}) \
              .set_packet(pk1) \
              .deliver()

            if da.get_error_success() != 0:
                self.log(f"[ALERT][FAIL] {node['universal_id']}: {da.get_error_success_msg()}")
            else:
                self.log(f"[ALERT] Delivered to {node['universal_id']}")

    def worker(self, config:dict = None, identity:IdentityObject = None):
        self.maybe_roll_day("nginx")
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
    agent = Agent()
    agent.boot()