# ╔══════════════════════════════════════════════════════════╗
# ║                  📡 DISCORD AGENT V3 📡                  ║
# ║     Matrix-Compatible · Swarm Speaker · Relay-Class     ║
# ╚══════════════════════════════════════════════════════════╝
import os
import threading
import json
import discord as discord_real
from discord.ext import commands
import asyncio

from agent.core.boot_agent import BootAgent
from agent.core.utils.swarm_sleep import interruptible_sleep

class DiscordAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args, tree_node)


        self.discord_client = None
        self.bot = None

        # Inject full tree_node so BootAgent sees config
        self.directives = tree_node if 'tree_node' in globals() else {}

        self.inbox_paths=['incoming']
        path = os.path.join(path_resolution["comm_path_resolved"], "incoming")
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
            self.log(f"[DISCORD] Watching {len(self.inbox_paths)} inbox(es).")
            while self.running:
                for inbox in self.inbox_paths:
                    if not os.path.exists(inbox):
                        continue
                    for file in os.listdir(inbox):
                        if file.endswith(".msg"):
                            fpath = os.path.join(inbox, file)
                            self.log(f"[DISCORD] Detected message file: {file}")
                            try:
                                with open(fpath, "r") as f:
                                    msg = json.load(f)
                                if self.bot:
                                    channel = self.bot.get_channel(self.channel_id)
                                    if channel:
                                        message = msg.get("msg") or msg.get("cause") or str(msg)
                                        self.log(f"[DISCORD] Sending: {message}")
                                        asyncio.run_coroutine_threadsafe(
                                            channel.send(f"📣 {message}"), self.bot.loop
                                        )
                                    else:
                                        self.log("[DISCORD] Channel not found.")
                                else:
                                    self.log("[DISCORD] Bot not yet ready.")
                                os.remove(fpath)
                                self.log(f"[DISCORD] Message dispatched + file removed.")
                            except Exception as e:
                                self.log(f"[DISCORD][ERROR] Failed to send .msg: {e}")
                interruptible_sleep(self, 5)
        except Exception as e:
            self.log(f"[DISCORD][FATAL] Payload watcher crashed: {e}")

    def on_alarm(self, payload):
        msg = f"🚨 [{payload['level'].upper()}] {payload['universal_id']} — {payload['cause']}"
    #    self.send_message_to_platform(msg)

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = DiscordAgent(path_resolution, command_line_args)
    agent.boot()
