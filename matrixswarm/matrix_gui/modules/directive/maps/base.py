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
        "target": ["config"],
        "fields": {
            "": ["port", "allowlist_ips"]
        },
        "proto_required": ["https", "wss"]
    },
}