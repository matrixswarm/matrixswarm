import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import json
import time
import traceback
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.cooldowns = {}  # key = alert signature, value = last_trigger_time
        self.exchange = None  # will be your dynamically loaded object
        self._initialized_from_tree = False


    def cmd_agent_config_update(self):
        try:
            exchange_name = self.tree_node.get("config", {}).get("exchange", "coingecko")

            try:
                mod_path = f"agent.crypto_alert.cmd.exchange.{exchange_name}"
                self.log(f"[EXCHANGE-LOADER] Attempting to load: {mod_path}")
                module = __import__(mod_path, fromlist=["Exchange"])
                self.exchange = module.Exchange(self)  # You can pass `self` to give the object agent access
                self.log(f"[EXCHANGE-LOADER] ✅ Loaded {exchange_name} exchange handler.")
            except Exception as e:
                self.exchange = None
                self.log(f"[EXCHANGE-LOADER][FAIL] {exchange_name}: {e}")

        except Exception as e:
            self.log(f"[INIT-FAIL] Could not load initial config: {e}")

    def packet_listener_post(self, config=None):
        if not self._initialized_from_tree:
            self.cmd_agent_config_update()

    def execute(agent, action):
        pair = action.get("pair")
        threshold = action.get("threshold")
        cooldown = action.get("cooldown", 300)

        price = agent.exchange.get_price(pair)
        if price is None:
            agent.log(f"[ACTION][SKIP] No price for {pair}")
            return

        key = f"{pair}:price_above:{threshold}"
        last = agent.cooldowns.get(key, 0)
        if time.time() - last < cooldown:
            return

        if price > threshold:
            agent.cooldowns[key] = time.time()
            agent.alert_operator(f"{pair} price is ABOVE {threshold} (now {price})")

    def should_trigger(self, key, price, threshold, mode, cooldown):
        last = self.cooldowns.get(key, 0)
        if time.time() - last < cooldown:
            return False

        if mode == "price_below" and price < threshold:
            return True
        if mode == "price_above" and price > threshold:
            return True

        return False

    def get_price(self, pair):
        try:
            if self.exchange:
                pair = self.tree_node.get("pair", None).get("pair", None)
                if pair:
                    self.exchange.get_price(pair)
                else:
                    raise
        except Exception as e:
            self.log(f"[PRICE-FETCH][ERROR] Failed to fetch price for {pair}: {e}", level="ERROR")
            err = str(e)
            stack = traceback.format_exc()
            self.log(f"[PRICE_FETCH][GET_PRICE][ERROR] {err}")
            self.log(stack)  # Optional: write full trace to logs

        return None

    def alert_operator(self, message):
        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({"handler": "cmd_send_alert_msg"})

        pk2 = self.get_delivery_packet("notify.alert.general", new=True)
        pk2.set_data({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "universal_id": self.command_line_args.get("universal_id", "unknown"),
            "level": "info",
            "msg": message,
            "formatted_msg": f"📈 Crypto Alert\n{message}",
            "cause": "Crypto Alert",
            "origin": self.command_line_args.get("universal_id", "unknown")
        })

        pk1.set_packet(pk2, "content")

        for node in self.get_nodes_by_role("hive.alert.send_alert_msg"):
            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
              .set_address([node["universal_id"]]) \
              .set_drop_zone({"drop": "incoming"}) \
              .set_packet(pk1) \
              .deliver()

if __name__ == "__main__":
    agent = Agent()
    agent.boot()
