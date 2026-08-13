from connection_group import ConnectionGroup, HttpsTransport, WsTransport
from websocket import WebSocketApp

def ws_connect(url, ssl_ctx, on_message, **proxy_kw):
    app = WebSocketApp(
        url,
        on_message=lambda ws, msg: on_message(msg),
        on_error=lambda ws, err: None,   # optional: surface/log
        on_close=lambda ws, code, msg: None,
    )

    sslopt = {"ssl_context": ssl_ctx}  # <-- CRITICAL

    # If you use an HTTP(S) proxy for WS, thread it through:
    run_kwargs = {"sslopt": sslopt}
    if proxy_kw:
        # websocket-client expects these keys
        if "http_proxy_host" in proxy_kw:
            run_kwargs["http_proxy_host"] = proxy_kw["http_proxy_host"]
        if "http_proxy_port" in proxy_kw:
            run_kwargs["http_proxy_port"] = proxy_kw["http_proxy_port"]
        if "proxy_type" in proxy_kw:
            run_kwargs["proxy_type"] = proxy_kw["proxy_type"]

    # This call blocks; your Transport.start() already runs it in a thread
    app.run_forever(**run_kwargs)
    return app

def list_directives_from_vault():
    # return [(universe_id, serial, cert_profile), ...]
    # TODO: pull from your unlocked vault structure
    return [
        ("universe_alpha", "serial_abc123", {
            "https_client_cert": "/path/client.crt",
            "https_client_key": "/path/client.key",
            "https_ca": "/path/ca.crt",
            "remote_pubkey": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
        })
    ]

def emit(event, payload):
    # Hook to your Qt signals / Ops tab
    print(f"EVT {event}: {payload if isinstance(payload, str) else ''}")

group = ConnectionGroup(
    id="group-alpha",
    name="Deployment Alpha",
    https=HttpsTransport("https", "192.168.1.2", 1111),
    wss=WsTransport("wss",  "192.168.1.2", 2222, connect_fn=ws_connect),
    emit=emit
)

# When user clicks [Connect] for this group:
group.connect(list_directives_fn=list_directives_from_vault)

# Later, test a round-trip ping:
def on_ping_reply(msg): print("PING REPLY:", msg)
# (call after status shows BOUND)
# group.send_cmd("cmd_ping", {"echo": "phoenix"}, on_reply=on_ping_reply)
