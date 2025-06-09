import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import importlib
import time
import traceback
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.name = "CryptoAgent"
        self.exchange = None
        self._initialized_from_tree = False
        self._private_config = self.tree_node.get("config", {})
        self._last_price = None
        self.trigger_hits = 0

    def cmd_update_agent_config(self):

        try:
            self._initialized_from_tree = True
            exchange_name = self._private_config.get("exchange", "coingecko")
            mod_path = f"crypto_alert.factory.cryptocurrency.exchange.{exchange_name}"

            self.log(f"Attempting to load: {mod_path}", block="exchange_loader")
            try:
                module = importlib.import_module(mod_path)
                importlib.reload(module)
                ExchangeClass = getattr(module, "Exchange")
                self.exchange = ExchangeClass(self)
                self.log(f"[EXCHANGE-LOADER] ✅ Loaded exchange handler: {exchange_name}")
            except Exception as e:
                self.log("Could not load exchange module '{exchange_name}", error=e)

        except Exception as e:
            self.log("Failed to initialize config", error=e)

    def worker(self,config:dict=None):

        if config:
            self.log(f"config loaded: {config}")

            if config.get("partial_config"):
                config = config.copy()  # avoid mutating the caller’s dict
                config.pop("partial_config", None)
                self._private_config.update(config)
                self.log("[WORKER] 🧩 Partial config merged.")
            else:
                self._private_config = config
                self.log("[WORKER] 🔁 Full config applied.")

            self._initialized_from_tree = False



        if not self._initialized_from_tree:
            self.cmd_update_agent_config()

        if not self._private_config.get("active", True):
            self.log("🔇 Agent marked inactive. Exiting cycle.")
            return

        trigger = self._private_config.get("trigger_type", "price_change_above")

        # Break it into base + direction (e.g., price_change_above → price_change + above)
        if "_" in trigger:
            base_trigger, direction = trigger.rsplit("_", 1)
        else:
            base_trigger = trigger
            direction = "above"

        if base_trigger == "price_change":
            self._run_price_change_monitor(direction)
        elif base_trigger == "price_delta":
            self._run_price_delta_monitor(direction)
        elif base_trigger == "price":
            self._run_price_threshold(direction)
        elif base_trigger == "asset_conversion":
            self._run_asset_conversion_check()
        else:
            self.log(f"[UNKNOWN TRIGGER] {trigger}")



        interval = int(self._private_config.get("poll_interval", 60))
        interruptible_sleep(self, interval)

    def _run_price_change_monitor(self, direction="above"):
        try:
            pair = self._private_config.get("pair", "BTC/USDT")
            threshold_pct = float(self._private_config.get("change_percent", 1.5))
            current = self.exchange.get_price(pair)
            if current is None:
                self.log("[CRYPTOAGENT][ERROR] No price received.")
                return

            if self._last_price is None:
                self._last_price = current
                self.log(f"[DEBUG] Initial price set to {self._last_price}")
                return

            delta = current - self._last_price
            delta_pct = abs(delta / self._last_price) * 100
            self.log(
                f"[DEBUG] Current: {current}, Previous: {self._last_price}, Δ = {delta:.2f}, Δ% = {delta_pct:.4f}%")

            condition = (direction == "above" and delta > 0) or (direction == "below" and delta < 0)

            if condition and delta_pct >= threshold_pct:
                self._alert(f"{pair} moved {delta_pct:.2f}% {direction.upper()} → from {self._last_price} to {current}")
                self._last_price = current

        except Exception as e:
            self.log("Price change failure", error=e)

    def _run_price_delta_monitor(self, direction="above"):
        try:
            pair = self._private_config.get("pair", "BTC/USDT")
            threshold_abs = float(self._private_config.get("change_absolute", 1000))
            current = self.exchange.get_price(pair)
            if current is None:
                return

            if self._last_price is None:
                self._last_price = current
                self.log(f"[DEBUG] Initial price set to {self._last_price}")
                return

            delta = current - self._last_price
            delta_abs = abs(delta)
            self.log(f"[DEBUG] Δ = {delta:.2f} vs threshold {threshold_abs:.2f}")

            condition = (direction == "above" and delta > 0) or (direction == "below" and delta < 0)

            if condition and delta_abs >= threshold_abs:
                self._alert(f"{pair} moved ${delta_abs:.2f} {direction.upper()} → from {self._last_price} to {current}")
                self._last_price = current

        except Exception as e:
            self.log(error=e)

    def _run_price_threshold(self, mode):
        try:
            pair = self._private_config.get("pair", "BTC/USDT")
            threshold = float(self._private_config.get("threshold", 0))
            current = self.exchange.get_price(pair)
            if current is None:
                return

            if mode == "above" and current > threshold:
                self._alert(f"{pair} is above threshold: {current} > {threshold}")
            elif mode == "below" and current < threshold:
                self._alert(f"{pair} is below threshold: {current} < {threshold}")

        except Exception as e:
            self.log(error=e)

    def _run_asset_conversion_check(self):
        try:
            from_asset = self._private_config.get("from_asset", "BTC")
            to_asset = self._private_config.get("to_asset", "ETH")
            from_amount = float(self._private_config.get("from_amount", 0.1))
            threshold = float(self._private_config.get("threshold", 3.0))

            pair1 = f"{from_asset}/USDT"
            pair2 = f"{to_asset}/USDT"
            price1 = self.exchange.get_price(pair1)
            price2 = self.exchange.get_price(pair2)

            if price1 is None or price2 is None:
                return

            value = from_amount * price1 / price2
            self.log(f"[DEBUG] {from_amount} {from_asset} = {value:.4f} {to_asset}")

            if value >= threshold:
                self._alert(f"{from_amount} {from_asset} = {value:.4f} {to_asset} (≥ {threshold})")

        except Exception as e:
            self.log("Conversion fail", error=e)

    def _alert(self, message):
        self.alert_operator(message)
        self._handle_trigger_limit()

    def _handle_trigger_limit(self):
        self.trigger_hits += 1
        limit_mode = self._private_config.get("limit_mode", "forever")

        if limit_mode == "forever":
            return

        # Hardened: handle None, empty string, garbage
        raw_limit = self._private_config.get("activation_limit", 1)
        try:
            max_triggers = int(raw_limit) if raw_limit is not None else 1
        except (TypeError, ValueError) as e:
            self.log("Invalid activation_limit value", error=e, block="TRIGGER-LIMIT")
            max_triggers = 1

        if self.trigger_hits >= max_triggers:
            self.log("[CRYPTOAGENT] 🎯 Max triggers reached. Marking agent inactive.")
            self._private_config["active"] = False
            self._save_config_patch()
            return  # stop further work this cycle

    def _save_config_patch(self):
        try:
            uid = self.command_line_args.get("universal_id", "unknown")
            patch = {
                "target_universal_id": uid,
                "config": {"active": False},
                "push_live_config": True,
                "respond_to": "crypto_gui_1",
                "handler_role": "hive.rpc.route",
                "handler": "cmd_rpc_route",
                "response_handler": "rpc_result_update_agent",
                "response_id": f"{uid}-deactivate"
            }

            pkt = self.get_delivery_packet("standard.command.packet")
            pkt.set_data({
                "handler": "cmd_update_agent",
                "content": patch
            })

            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
                .set_address(["matrix"]) \
                .set_drop_zone({"drop": "incoming"}) \
                .set_packet(pkt) \
                .deliver()

            if da.get_error_success() == 0:
                self.log("[AGENT] Inactivation patch delivered.")
            else:
                self.log(f"[AGENT][PATCH-FAIL] {da.get_error_success_msg()}")

        except Exception as e:
            self.log("Error saving config patch", error=e)

    def _self_destruct(self):
        try:
            pk = self.get_delivery_packet("standard.command.packet")
            pk.set_data({
                "handler": "cmd_delete_agent",
                "content": {
                    "target_universal_id": self.command_line_args.get("universal_id", "unknown")
                }
            })
            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
              .set_address(["matrix"]) \
              .set_drop_zone({"drop": "incoming"}) \
              .set_packet(pk) \
              .deliver()

            if da.get_error_success() == 0:
                self.log("[CRYPTOAGENT] ☠️ Self-destruct packet sent.")
            else:
                self.log(f"[CRYPTOAGENT][SELF-DESTRUCT-FAIL] {da.get_error_success_msg()}")

        except Exception as e:
            self.log(error=e)

    def alert_operator(self, message):

        alert_handler = self._private_config.get("alert_handler")
        alert_role = self._private_config.get("alert_role")

        if not all([alert_handler, alert_role]):
            self.log("Alert dispatch missing routing fields", block="ALERT_HANDLER")
            return

        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({"handler": alert_handler})

        pk2 = self.get_delivery_packet("notify.alert.general", new=True)
        pk2.set_data({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "universal_id": self.command_line_args.get("universal_id", "unknown"),
            "level": "critical",
            "msg": message,
            "formatted_msg": f"📈 Crypto Alert\n{message}",
            "cause": "Crypto Alert",
            "origin": self.command_line_args.get("universal_id", "unknown")
        })

        pk1.set_packet(pk2, "content")

        for node in self.get_nodes_by_role(alert_role):
            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
              .set_address([node["universal_id"]]) \
              .set_drop_zone({"drop": "incoming"}) \
              .set_packet(pk1) \
              .deliver()

            if da.get_error_success() == 0:
                self.log(f"[ALERT] Delivered to {node['universal_id']}")
            else:
                self.log(f"[ALERT][FAIL] {node['universal_id']}: {da.get_error_success_msg()}")

if __name__ == "__main__":
    agent = Agent()
    agent.boot()

