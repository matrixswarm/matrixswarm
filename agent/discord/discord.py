# ╔══════════════════════════════════════════════════════════╗
# ║                  📡 DISCORD AGENT V3 📡                  ║
# ║     Matrix-Compatible · Swarm Speaker · Relay-Class     ║
# ╚══════════════════════════════════════════════════════════╝

import os
import sys
import threading
import json
import discord as discord_real
from discord.ext import commands
import asyncio

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])


from agent.core.boot_agent import BootAgent
from agent.core.utils.swarm_sleep import interruptible_sleep

class DiscordAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.discord_client = None

        config = tree_node.get("config", {}) if 'tree_node' in globals() else {}
        self.token = config.get("bot_token")
        self.channel_id = int(config.get("channel_id", 0))
        self.name = "DiscordAgentV3e"

    def worker(self):
        self.log("[DISCORD] Worker alive, idling.")
        while self.running:
            interruptible_sleep(self, 5)

    def post_boot(self):
        self.log("[DISCORD] Payload watcher thread starting...")
        threading.Thread(target=self.payload_watcher, daemon=True).start()

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

            self.discord_client = self.bot

            @self.bot.event
            async def on_ready():
                self.log(f"[DISCORD] Connected as {self.bot.user}")
                channel = self.bot.get_channel(self.channel_id)
                if channel:
                    await channel.send("🧠 DiscordAgent V3e online and responding.")

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

            self.bot.run(self.token)

        except Exception as e:
            self.log(f"[DISCORD][ERROR] Client thread failed: {e}")
            print(f"❌ Exception during Discord client run: {e}")

    def payload_watcher(self):
        try:
            path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
            self.log(f"[DISCORD] Watching: {path}")
            while self.running:
                for file in os.listdir(path):
                    if file.endswith(".msg"):
                        full_path = os.path.join(path, file)
                        with open(full_path, "r") as f:
                            msg = json.load(f)
                            channel = self.discord_client.get_channel(self.channel_id)
                            if channel:
                                asyncio.run_coroutine_threadsafe(
                                    channel.send(f"📣 {msg.get('msg')}"), self.discord_client.loop
                                )
                        os.remove(full_path)
                interruptible_sleep(self, 5)
        except Exception as e:
            self.log(f"[DISCORD][ERROR][PAYLOAD] {e}")
            print(f"❌ Payload watcher failed: {e}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = DiscordAgent(path_resolution, command_line_args)
    agent.boot()
