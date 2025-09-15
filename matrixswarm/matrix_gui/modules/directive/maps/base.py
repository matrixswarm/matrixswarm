CERT_INJECTION_MAP = {
    "packet_signing": {
        "target": ["config", "security", "signing"],
        "fields": {
            "in": ["remote_pubkey"],
            "out": ["privkey"],
        },
        "include_serial": True
    },
    "connection_cert": {
        "target": ["config", "security", "connection"],
        "fields": {
            "server_cert": ["cert", "key", "serial", "spki_pin"],
            "client_cert": ["cert", "key", "serial", "spki_pin"],
            "ca_root": ["cert", "key", "serial"]
        },
        "proto_required": ["https", "wss"]
    },
    "connection": {
        'wss':{
            "target": ["config"],
            "fields": ["port", "allowlist_ips"]
        },
        'https':{
            "target": ["config"],
            "fields": ["port", "allowlist_ips"]
        },
        'discord':{
            "target": ["config"],
            "fields": ["bot_token", "channel_id"],
        },
        'telegram':{
            "target": ["config"],
            "fields": ["bot_token", "chat_id"],
        },
        'openai': {
            "target": ["config"],
            "fields": ["api_key"],
        },
    },

}