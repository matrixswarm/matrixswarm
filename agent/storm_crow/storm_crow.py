import sys
import os
import requests
import traceback
import time

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.name = "StormCrow"
        self.api_key = os.getenv("WEATHER_API_KEY")  # OpenWeather or NWS-style
        self.lat = os.getenv("WEATHER_LAT", "46.87")
        self.lon = os.getenv("WEATHER_LON", "-68.01")
        self.alert_endpoint = f"https://api.weather.gov/alerts/active?point={self.lat},{self.lon}"
        self.last_alert_ids = set()

    def pre_boot(self):
        self.log("[STORMCROW] Pre-boot weather alert initialization complete.")

    def post_boot(self):
        self.log("[STORMCROW] Agent is live and scanning the sky.")

    def fetch_alerts(self):
        try:
            resp = requests.get(self.alert_endpoint, headers={"User-Agent": "StormCrow-Agent"}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features")
            if not isinstance(features, list):
                self.log(f"[STORMCROW][ERROR] Unexpected response shape: {data}")
                return []
            return features
        except requests.exceptions.RequestException as e:
            err = str(e)
            stack = traceback.format_exc()
            self.log(f"[STORMCROW]['FETCH_ALERTS][NETWORK-FAIL] {err}")
            self.log(stack)  # Optional: write full trace to logs
        except Exception as e:
            err = str(e)
            stack = traceback.format_exc()
            self.log(f"[STORMCROW]['FETCH_ALERTS][NETWORK-FAIL]] Unhandled fetch failure:  {err}")
            self.log(stack)  # Optional: write full trace to logs

        return []

    def alert_operator(self, title, message):
        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({"handler": "cmd_send_alert_msg"})

        pk2 = self.get_delivery_packet("notify.alert.general")
        pk2.set_data({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "universal_id": self.command_line_args.get("universal_id", "unknown"),
            "level": "warning",
            "msg": message,
            "formatted_msg": f"🌩 {title}\n{message}",
            "cause": "StormCrow Severe Weather Alert",
            "origin": self.command_line_args.get("universal_id", "unknown")
        })

        pk1.set_packet(pk2, "content")

        alert_nodes = self.get_nodes_by_role("hive.alert.send_alert_msg")
        if not alert_nodes:
            self.log("[STORMCROW][ALERT] No alert-compatible agents found.")
            return

        for node in alert_nodes:
            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
              .set_address([node["universal_id"]]) \
              .set_drop_zone({"drop": "incoming"}) \
              .set_packet(pk1) \
              .deliver()

            if da.get_error_success() != 0:
                self.log(f"[STORMCROW][ALERT][FAIL] {node['universal_id']}: {da.get_error_success_msg()}")
            else:
                self.log(f"[STORMCROW][ALERT] Delivered to {node['universal_id']}")

    def worker(self, config: dict = None):
        try:
            self.log("[STORMCROW] Worker loop scanning for severe weather alerts...")
            alerts = self.fetch_alerts()
            if not alerts:
                self.log("[STORMCROW] ✅ NWS returned no alerts.")
            for item in alerts:
                alert_id = item.get("id")
                props = item.get("properties", {})
                event = props.get("event")
                severity = props.get("severity")
                area = props.get("areaDesc")
                headline = props.get("headline")
                issued = props.get("sent")

                if alert_id not in self.last_alert_ids:
                    self.last_alert_ids.add(alert_id)
                    msg = f"{event} | {severity} | {area}\n📰 {headline}\n📅 Issued: {issued}"
                    self.log(f"[STORMCROW] ⚠️ NEW ALERT: {event} | {severity} | {area}")
                    self.log(f"[STORMCROW] 📰 {headline} (Issued: {issued})")
                    self.alert_operator(event, msg)

            interruptible_sleep(self, 900)

        except Exception as e:
            err = str(e)
            stack = traceback.format_exc()
            self.log(f"[STORMCROW] Worker crashed mid-cycle: {err}")
            self.log(stack)  # Optional: write full trace to logs
            interruptible_sleep(self, 60)


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
