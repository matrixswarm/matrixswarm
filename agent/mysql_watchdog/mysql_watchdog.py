# ======== 🧠 CAPITAL_GPT: MISSION STRATEGIST ========
# One mission. One mind. No mercy.
import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import time
import subprocess
import json
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep
from datetime import datetime, timedelta

class Agent(BootAgent):
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
        self.daily_stats = {
            "date": self.today(),
            "restart_count": 0,
            "total_uptime_sec": 0,
            "total_downtime_sec": 0,
            "last_status": None,
            "last_status_change": time.time()
        }

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
            self.daily_stats["restart_count"] += 1
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
        last = self.daily_stats["last_status"]
        elapsed = now - self.daily_stats["last_status_change"]

        # If state changed (or first run), update timing
        if last is not None:
            if last:
                self.daily_stats["total_uptime_sec"] += elapsed
            else:
                self.daily_stats["total_downtime_sec"] += elapsed

        if last != is_running:
            self.log(f"[WATCHDOG] MySQL status changed → {'UP' if is_running else 'DOWN'}")

            if is_running and self.last_alerted_status == "DOWN":
                self.alert_operator("✅ MySQL has recovered and is now online.")
                self.last_alerted_status = "UP"

            elif not is_running:
                self.last_alerted_status = "DOWN"

        self.daily_stats["last_status"] = is_running
        self.daily_stats["last_status_change"] = now

    def maybe_roll_day(self):
        today = self.today()
        if self.daily_stats["date"] != today:
            self.persist_daily_log()
            self.daily_stats = {
                "date": today,
                "restart_count": 0,
                "total_uptime_sec": 0,
                "total_downtime_sec": 0,
                "last_status": None,
                "last_status_change": time.time()
            }

    def is_socket_accessible(self):
        return os.path.exists(self.socket_path)

    def is_mysql_listening(self):
        try:
            out = subprocess.check_output(["ss", "-ltn"])
            return f":{self.mysql_port}".encode() in out
        except Exception as e:
            self.log(f"[WATCHDOG][ERROR] Failed to scan ports: {e}")
            return False

    def persist_daily_log(self):
        comm_dir = os.path.join(self.path_resolution["comm_path"], "mysql-watchdog")
        os.makedirs(comm_dir, exist_ok=True)
        fname = f"restarts_{self.daily_stats['date']}.log"
        full_path = os.path.join(comm_dir, fname)
        with open(full_path, "w") as f:
            json.dump(self.daily_stats, f, indent=2)
        self.log(f"[WATCHDOG] 📊 Daily log written to {fname}")
        uptime = self.daily_stats["total_uptime_sec"]
        downtime = self.daily_stats["total_downtime_sec"]
        total = uptime + downtime

        if total > 0 and (uptime / total) < 0.9:
            self.alert_operator(f"⚠️ MySQL uptime dropped to {uptime / total:.2%} today.")



    def worker_pre(self):
        self.log(f"[WATCHDOG] Watching systemd unit: {self.service_name}")

    def worker(self):

        self.maybe_roll_day()
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
        Uses Swarm packet + delivery agent pipeline to send structured alerts.
        """
        if not message:
            message = "🚨 MySQL REFLEX TERMINATION\n\nReflex loop failed (exit_code = -1)"

        pk = self.get_delivery_packet("notify.alert.general", new=True)
        pk.set_data({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": self.command_line_args.get("universal_id", "unknown"),
                "level": "critical",
                "msg": message,
                "formatted_msg": f"📣 Swarm Message\n{message}",
                "cause": "MySQL Watchdog Alert",
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


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
