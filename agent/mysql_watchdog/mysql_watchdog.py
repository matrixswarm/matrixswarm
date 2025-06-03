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
        self.name = "MySQLWatchdog"
        self.last_restart = None
        self.failed_restart_count = 0
        self.disabled = False
        self.alert_fired = False
        self.last_alerted_status = None  # None, "DOWN", or "UP"
        self.last_alerts = {}
        self.alert_cooldown_sec = 600
        cfg = self.tree_node.get("config", {})
        self.interval = cfg.get("check_interval_sec", 20)
        self.mysql_port = cfg.get("mysql_port", 3306)
        self.socket_path = cfg.get("socket_path", "/var/run/mysqld/mysqld.sock")
        self.failed_restart_limit = cfg.get("restart_limit", 3)
        self.alert_thresholds = cfg.get("alert_thresholds", {"uptime_pct_min": 90, "slow_restart_sec": 10})
        self.service_name = cfg.get("service_name", "mysql")
        self.comm_targets = cfg.get("comm_targets", [])
        self.stats = {
            "date": self.today(),
            "restarts": 0,
            "uptime_sec": 0,
            "downtime_sec": 0,
            "last_status": None,
            "last_status_change": time.time()
        }
        # test writing summary
        self.stats["date"] = "1900-01-01"

    def today(self):
        return datetime.now().strftime("%Y-%m-%d")

    def is_mysql_running(self):
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "--quiet", self.service_name],
                check=False
            )
            return result.returncode == 0
        except Exception as e:
            self.log(f"[WATCHDOG][ERROR] Failed to check MySQL status: {e}")
            return False

    def restart_mysql(self):
        if self.disabled:
            self.log("[WATCHDOG][DISABLED] Agent is disabled due to repeated failures.")
            return

        self.log("[WATCHDOG] Attempting to restart MySQL...")
        try:
            subprocess.run(["systemctl", "restart", self.service_name], check=True)
            self.log("[WATCHDOG] ✅ MySQL successfully restarted.")
            self.post_restart_check()
            self.last_restart = time.time()
            self.stats["restarts"] += 1
            self.failed_restart_count = 0  # reset on success
        except Exception as e:
            self.failed_restart_count += 1
            self.log(f"[WATCHDOG][FAIL] Restart failed: {e}")
            if self.failed_restart_count >= self.failed_restart_limit:
                self.disabled = True
                self.alert_operator("🛑 MySQL watchdog disabled after repeated restart failures.")
                self.log("[WATCHDOG][DISABLED] Max restart attempts reached. Watchdog disabled.")

    def update_status_metrics(self, is_running):
        now = time.time()
        last = self.stats.get("last_status")
        elapsed = now - self.stats.get("last_status_change", now)

        # If state changed (or first run), update timing
        if last is not None:
            if last:
                self.stats["uptime_sec"] += elapsed
            else:
                self.stats["downtime_sec"] += elapsed

        if last != is_running:
            self.log(f"[WATCHDOG] MySQL status changed → {'UP' if is_running else 'DOWN'}")

            if is_running and self.last_alerted_status == "DOWN":
                self.alert_operator("✅ MySQL has recovered and is now online.")
                self.last_alerted_status = "UP"

            elif not is_running:
                self.last_alerted_status = "DOWN"

        self.stats["last_status"] = is_running
        self.stats["last_status_change"] = now

    def is_socket_accessible(self):
        return os.path.exists(self.socket_path)

    def is_mysql_listening(self):
        try:
            out = subprocess.check_output(["ss", "-ltn"])
            return f":{self.mysql_port}".encode() in out
        except Exception as e:
            self.log(f"[WATCHDOG][ERROR] Failed to scan ports: {e}")
            return False

    def worker_pre(self):
        self.log(f"[WATCHDOG] Watching systemd unit: {self.service_name}")

    def worker(self, config:dict = None):

        self.maybe_roll_day("mysql")
        running = self.is_mysql_running()
        self.update_status_metrics(running)

        if running and not self.is_mysql_listening() and not self.is_socket_accessible():
            self.log("[WATCHDOG][WARN] MySQL is running but not accessible on port or socket.")
            self.alert_operator(f"⚠️ MySQL is running but neither port {self.mysql_port} nor socket {self.socket_path} is open.")

        if running:
            self.log("[WATCHDOG] ✅ MySQL is running.")
        else:
            self.log("[WATCHDOG] ❌ MySQL is NOT running.")

            # Fire alert immediately even if it might recover quickly
            if self.should_alert("mysql-down"):
                self.alert_operator( "❌ MySQL appears to be down. Attempting restart...")

            self.last_alerted_status = "DOWN"
            self.restart_mysql()
        interruptible_sleep(self, self.interval)

    def should_alert(self, key):
        now = time.time()
        last = self.last_alerts.get(key, 0)
        if now - last > self.alert_cooldown_sec:
            self.last_alerts[key] = now
            return True
        return False

    def post_restart_check(self):
        time.sleep(5)
        if not self.is_mysql_listening():
            self.log(f"[WATCHDOG][CRIT] MySQL restarted but port {self.mysql_port} is still not listening.")
            self.alert_operator("🚨 MySQL restarted but never began listening on port {self.mysql_port}.")

    def alert_operator(self, message=None):
        """
        Uses packet + delivery agent system to send alert to all comms.
        """
        if not message:
            message = "🚨 MYSQL REFLEX TERMINATION\n\nReflex loop failed (exit_code = -1)"

        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({"handler": "cmd_send_alert_msg"})

        pk2 = self.get_delivery_packet("notify.alert.general", new=True)
        pk2.set_data({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": self.command_line_args.get("universal_id", "unknown"),
                "level": "critical",
                "msg": message,
                "formatted_msg": f"📣 Swarm Message\n{message}",
                "cause": "Mysql Sentinel Alert",
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

if __name__ == "__main__":
    agent = Agent()
    agent.boot()
