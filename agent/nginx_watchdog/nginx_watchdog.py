import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import subprocess
import time
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep
from datetime import datetime
from core.mixin.agent_summary_mixin import AgentSummaryMixin

class Agent(BootAgent, AgentSummaryMixin):
    def __init__(self):
        super().__init__()
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
            "last_change": time.time(),
        }

        #test writing summary
        #self.stats["date"] = "1900-01-01"


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

        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({"handler": "cmd_send_alert_msg"})

        pk2 = self.get_delivery_packet("notify.alert.general", new=True)
        pk2.set_data({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": self.command_line_args.get("universal_id", "unknown"),
                "level": "critical",
                "msg": message,
                "formatted_msg": f"📣 Swarm Message\n{message}",
                "cause": "Nginx Sentinel Alert",
                "origin": self.command_line_args.get("universal_id", "unknown")
        })

        pk1.set_packet(pk2, "content")

        alert_nodes = self.get_nodes_by_role("hive.alert.send_alert_msg")
        if not alert_nodes:
            self.log("[WATCHDOG][ALERT] No alert-compatible agents found.")
            return

        for node in alert_nodes:
            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
                .set_address([node["universal_id"]]) \
                .set_drop_zone({"drop": "incoming"}) \
                .set_packet(pk1) \
                .deliver()

            if da.get_error_success() != 0:
                self.log(f"[ALERT][DELIVERY-FAIL] {node['universal_id']}: {da.get_error_success_msg()}")
            else:
                self.log(f"[ALERT][DELIVERED] Alert sent to {node['universal_id']}")

    def worker(self, config:dict = None):
        self.maybe_roll_day("nginx")
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
    agent = Agent()
    agent.boot()
