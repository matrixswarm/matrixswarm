
# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

import ssl
import time
import threading
import asyncio
import websockets
import json
import os

from core.boot_agent import BootAgent

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)

        config = self.tree_node.get("config", {})

        self.clients = set()

        self.port = config.get("port", 8765)
        self.clients = set()
        self.loop = None
        self.websocket_ready = False
        self.cert_dir = "socket_certs"

    def worker_pre(self):
        self.log("[WS] Launching WebSocket thread...")
        threading.Thread(target=self.start_socket_loop, daemon=True).start()

    def start_socket_loop(self):
        try:
            self.log("[WS] Booting WebSocket TLS thread...")
            time.sleep(1)

            cert_path = os.path.join(self.cert_dir, "server.crt")
            key_path = os.path.join(self.cert_dir, "server.key")

            if not os.path.exists(cert_path) or not os.path.exists(key_path):
                self.log(f"[WS][FATAL] Missing cert/key file at {cert_path} or {key_path}")
                self.running = False
                return

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop

            async def launch():
                self.log("[WS] Preparing SSL context...")
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path)

                self.log(f"[WS] Attempting to bind WebSocket on port {self.port}...")
                server = await websockets.serve(
                    self.websocket_handler,
                    "0.0.0.0",
                    self.port,
                    ssl=ssl_context
                )

                self.websocket_ready = True
                self.log(f"[WS] ✅ SECURE WebSocket bound on port {self.port} (TLS enabled)")
                await server.wait_closed()

            loop.run_until_complete(launch())
            loop.run_forever()

        except Exception as e:
            self.log(f"[WS][FATAL] WebSocket startup failed: {e}")
            self.running = False

    def msg_health_report(self, content, packet):
        self.log(f"[RELAY] Received health report for {content.get('target_universal_id', '?')}")

    async def websocket_handler(self, websocket, path):

        self.log("[WS][TRACE] >>> websocket_handler() CALLED <<<")
        self.log("[WS] HANDLER INIT - Client added")
        # Add the client securely to the clients set
        self.clients.add(websocket)
        self.log("[WS] HANDLER INIT - Client added")

        try:
            while True:
                self.log("[WS] Awaiting message...")

                try:
                    # Await a message from the client
                    message = await websocket.recv()
                    self.log(f"[WS][RECEIVED] {repr(message)}")

                    # Attempt to decode JSON (if applicable)
                    try:
                        data = json.loads(message)
                        self.log(f"[WS][VALID MESSAGE] {data}")
                    except json.JSONDecodeError:
                        self.log("[WS][ERROR] Malformed JSON received")
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Invalid JSON format"
                        }))
                        continue

                    # Respond with acknowledgment
                    await websocket.send(json.dumps({
                        "type": "ack",
                        "echo": message
                    }))

                except websockets.ConnectionClosed as cc:
                    # Handle a graceful client disconnection
                    self.log(f"[WS][DISCONNECT] Client disconnected gracefully: ({cc.code}) {cc.reason}")
                    break

                except Exception as e:
                    # Handle unexpected errors during message handling
                    self.log(f"[WS][ERROR] Unexpected error during message processing: {e}")
                    break

        finally:
            # Ensure client is removed from the set upon disconnect
            self.clients.discard(websocket)
            self.log(f"[WS] Client disconnected and removed. Active clients: {len(self.clients)}")

    def msg_broadcast(self, content, packet):
        if not hasattr(self, "loop") or self.loop is None:
            self.log("[WS][REFLEX][SKIP] Event loop not ready.")
            return

        if not getattr(self, "websocket_ready", False):
            self.log("[WS][REFLEX][WAITING] Socket not bound.")
            return

        try:
            data = json.dumps(packet)
            dead = []
            for client in self.clients:
                try:
                    asyncio.run_coroutine_threadsafe(client.send(data), self.loop)
                except Exception:
                    dead.append(client)

            for c in dead:
                self.clients.discard(c)

            self.log(f"[WS][REFLEX] Broadcasted to {len(self.clients)} clients.")
        except Exception as e:
            self.log(f"[WS][REFLEX][ERROR] {e}")


if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()