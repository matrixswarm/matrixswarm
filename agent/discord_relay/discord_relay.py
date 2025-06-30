import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
# ╔══════════════════════════════════════════════════════════╗
# ║                  📡 DISCORD AGENT V3 📡                  ║
# ║     Matrix-Compatible · Swarm Speaker · Relay-Class     ║
# ╚══════════════════════════════════════════════════════════╝

import threading
import discord as discord_real
from discord.ext import commands
import asyncio

from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep
from core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject

class Agent(BootAgent):
    def __init__(self):
        super().__init__()

        self.discord_client = None
        self.bot = None

        # Inject full tree_node so BootAgent sees config
        self.directives = self.tree_node

        self.inbox_paths=['incoming']
        path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(path, exist_ok=True)
        self.inbox_paths.append(path)

        # Local config for this agent
        config = self.directives.get("config", {})
        self.token = config.get("bot_token")
        self.channel_id = int(config.get("channel_id", 0))
        self.name = "DiscordAgentV3e"

    def worker_pre(self):
        self.log("[DISCORD] Worker alive, idling.")

    def worker(self, config:dict = None, identity:IdentityObject = None):

        interruptible_sleep(self, 2320)

    def post_boot(self):
        self.log("[DISCORD] Payload watcher thread starting...")

        self.log("[DISCORD] Starting client thread...")
        threading.Thread(target=self.start_discord_client, daemon=True).start()

    def start_discord_client(self):
        def runner():
            try:
                print("[DISCORD] Setting up event loop...")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                intents = discord_real.Intents.default()
                intents.messages = True
                intents.message_content = True

                self.bot = commands.Bot(command_prefix="!", intents=intents)

                @self.bot.event
                async def on_ready():
                    print("[ON_READY] Triggered!")
                    self.log(f"[DISCORD] Connected as {self.bot.user}")
                    for guild in self.bot.guilds:
                        for channel in guild.text_channels:
                            print(f"[DEBUG] {channel.name} — {channel.id}")
                    try:
                        channel = await self.bot.fetch_channel(self.channel_id)
                        await channel.send("DiscordAgent V3e online and responding.")
                    except Exception as e:
                        self.log(f"[DISCORD][ERROR] Channel access failed: {e}")

                async def run_bot():
                    print("[DISCORD] run_bot() starting...")
                    await self.bot.start(self.token)

                loop.create_task(run_bot())
                loop.run_forever()

            except Exception as e:
                self.log(f"[DISCORD][ERROR] Client thread failed: {e}")
                import traceback
                traceback.print_exc()

        # Launch in a dedicated thread
        threading.Thread(target=runner, daemon=True).start()

    def cmd_send_alert_msg(self, content, packet, identity:IdentityObject = None):
        try:
            message = self.format_message(content)
            self.send_to_discord(message)
            self.log("[DISCORD] Message relayed successfully.")
        except Exception as e:
            self.log(f"[DISCORD][ERROR] Failed to relay message: {e}")

    def send_to_discord(self, message):
        if not self.bot or not self.channel_id:
            self.log("[DISCORD][ERROR] Bot not ready or channel ID missing.")
            return
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                asyncio.run_coroutine_threadsafe(channel.send(message), self.bot.loop)
            else:
                self.log("[DISCORD][ERROR] Channel not found.")
        except Exception as e:
            self.log(f"[DISCORD][ERROR] Discord delivery failed: {e}")

    def format_message(self, data):
        return data.get("formatted_msg") or data.get("msg") or "[SWARM] No content."

    def on_alarm(self, payload):
        msg = f"[{payload['level'].upper()}] {payload['universal_id']} — {payload['cause']}"
    #    self.send_message_to_platform(msg)

if __name__ == "__main__":
    agent = Agent()
    agent.boot()
