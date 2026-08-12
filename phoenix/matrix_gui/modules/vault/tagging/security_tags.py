def get_security_tags():
    return {
        "queen": {
            "signing": ["privkey", "remote_pubkey"],
            "serial": ["serial"]
        },
        "perimeter_https": {
            "signing": ["privkey", "remote_pubkey"],
            "connection": ["cert", "key", "ca", "serial", "spki_pin"],
            "serial": ["serial"]
        },
        "perimeter_websocket": {
            "signing": ["privkey", "remote_pubkey"],
            "connection": ["cert", "key", "ca", "serial", "spki_pin"],
            "serial": ["serial"]
        }
    }
