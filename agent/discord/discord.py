# ╔══════════════════════════════════════════════════════════╗
# ║                  📡 DISCORD AGENT V3 📡                  ║
# ║     Matrix-Compatible · Swarm Speaker · Relay-Class     ║
# ╚══════════════════════════════════════════════════════════╝

# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"
import os
import sys
sys.path.insert(0, "/root/miniconda3/lib/python3.12/site-packages")
import threading
import json
import discord as discord_real
from discord.ext import commands
import asyncio

from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)

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

    def worker(self):

        interruptible_sleep(self, 2320)

    def post_boot(self):
        self.log("[DISCORD] Payload watcher thread starting...")

        self.log("[DISCORD] Starting client thread...")
        threading.Thread(target=self.start_discord_client, daemon=True).start()

    def start_discord_client(self):
        try:
            self.log(f"[DISCORD] Client starting... Token length: {len(self.token)}")
            print(f"🧠 Token preview: {self.token[:10]}...{self.token[-5:]}")

            intents = discord_real.Intents.default()
            intents.messages = True
            intents.message_content = True

            self.bot = commands.Bot(command_prefix="!", intents=intents)

            @self.bot.event
            async def on_ready():
                self.log(f"[DISCORD] Connected as {self.bot.user}")
                channel = self.bot.get_channel(self.channel_id)
                if channel:
                    await channel.send("🧠 DiscordAgent V3e online and responding.")
                else:
                    self.log(f"[DISCORD][ERROR] Channel ID {self.channel_id} not found!")

            @self.bot.command()
            async def status(ctx):
                await ctx.send("✅ Swarm is operational.")

            @self.bot.command()
            async def guest(ctx, alias: str = "Unknown", *, motto: str = "No motto."):
                try:
                    self.log(f"[DISCORD][GUEST] alias={alias}, motto={motto}")
                    await ctx.send(f"👤 Guest logged: {alias} — \"{motto}\"")
                except Exception as e:
                    self.log(f"[DISCORD][ERROR][GUEST] {e}")
                    await ctx.send("⚠️ Failed to log guest entry.")

            # Launch in a clean async event loop
            async def run_bot():
                await self.bot.start(self.token)

            threading.Thread(target=lambda: asyncio.run(run_bot()), daemon=True).start()

        except Exception as e:
            self.log(f"[DISCORD][ERROR] Client thread failed: {e}")
            import traceback
            traceback.print_exc()

    def msg_send_packet_incoming(self, content, packet):
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
        msg = f"🚨 [{payload['level'].upper()}] {payload['universal_id']} — {payload['cause']}"
    #    self.send_message_to_platform(msg)

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
