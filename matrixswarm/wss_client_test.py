import asyncio
import ssl
import websockets
import json
import time

async def run():
    uri = "wss://localhost:8765"

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_cert_chain("socket_certs/client.crt", "socket_certs/client.key")
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE  # WARNING: Dev only

    try:
        async with websockets.connect(uri, ssl=ssl_context) as ws:
            print("[CLIENT] Connected to relay.")
            await ws.send(json.dumps({
                "type": "diagnostic",
                "msg": "test from standalone client",
                "timestamp": time.time()
            }))
            print("[CLIENT] Sent test packet.")
            try:
                while True:
                    msg = await ws.recv()
                    print(f"[CLIENT] Received: {msg}")
            except websockets.exceptions.ConnectionClosed as e:
                print(f"[CLIENT] Connection closed: {e}")
    except Exception as e:
        print(f"[CLIENT] Connection failed: {e}")

asyncio.run(run())