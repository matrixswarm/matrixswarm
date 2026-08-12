def preprocess_python_to_json(self, text: str) -> str:
    # Strip comments and non-JSON junk at top
    lines = text.strip().splitlines()
    clean_lines = []
    for line in lines:
        if line.strip().startswith(("import", "from ", "load_dotenv", "#")):
            continue
        if "matrix_directive" in line and "=" in line:
            # Strip prefix like: matrix_directive = {...
            line = line.split("=", 1)[1].strip()
        clean_lines.append(line)
    return "\n".join(clean_lines)

def convert_bools_to_ints(obj):
    if isinstance(obj, dict):
        return {k: convert_bools_to_ints(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_bools_to_ints(v) for v in obj]
    elif isinstance(obj, bool):
        return int(obj)
    return obj

def inject_all_agents_security(tree, cert_profile, serial=None):
    if isinstance(tree, dict):
        if "security-tag" in tree:
            inject_security_by_tag(tree, cert_profile, serial)
        for v in tree.values():
            inject_all_agents_security(v, cert_profile, serial)
    elif isinstance(tree, list):
        for item in tree:
            inject_all_agents_security(item, cert_profile, serial)

def inject_security_by_tag(agent, cert_profile, serial=None):
    config = agent.get("config", {})
    tag = agent.get("security-tag")

    if not tag:
        print(f"[SEC-INJECT][SKIP] No security-tag for agent '{agent.get('name')}'")
        return

    if tag not in cert_profile:
        print(f"[SEC-INJECT][SKIP] Tag '{tag}' not in cert_profile for agent '{agent.get('name')}'")
        return

    tag_profile = cert_profile[tag]
    sec_block = {
        "signing": {
            "privkey": tag_profile["privkey"],
            "remote_pubkey": tag_profile["remote_pubkey"]
        }
    }

    is_matrix = agent.get("name", "").lower().startswith("matrix")
    if "cert" in tag_profile and not is_matrix:
        sec_block["connection"] = {
            "cert": tag_profile["cert"],
            "key": tag_profile.get("key", ""),
            "ca": tag_profile.get("ca", ""),
            "serial": tag_profile.get("serial") or serial,
            "spki_pin": tag_profile.get("spki_pin")
        }

    print(f"[SEC-INJECT] {agent.get('name')} ← tag='{tag}' serial='{sec_block.get('connection', {}).get('serial', '—')}'")

    # *** FORCIBLY REPLACE, do not append or keep old ***
    config["security"] = [sec_block]
    agent["config"] = config


def replace_serial_tags(obj, serial):
    if isinstance(obj, dict):
        return {k: replace_serial_tags(v, serial) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_serial_tags(i, serial) for i in obj]
    elif isinstance(obj, str):
        return obj.replace("##DIRECTIVE_SERIAL##", serial)
    else:
        return obj

def purge_env_fields(obj):
    ENV_MARKERS = {
        "bot_token": "##SECRET_DISCORD_TOKEN##",
        "chat_id": "##SECRET_CHAT_ID##",
        "email_pass": "##SECRET_EMAIL_PASS##",
        "smtp_user": "##SECRET_SMTP_USER##",
        "smtp_pass": "##SECRET_SMTP_PASS##",
        "api_key": "##SECRET_API_KEY##",
        "telegram_token": "##SECRET_TELEGRAM_TOKEN##"
    }

    def clean(k, v):
        if isinstance(v, str):
            for key, tag in ENV_MARKERS.items():
                print(f"[PURGE] Replaced '{k}' with '{tag}'")
                if key.lower() in k.lower() or key.lower() in v.lower():
                    return tag
            if "os.getenv" in v or "load_dotenv" in v:
                return "<ENV_REMOVED>"
        if v is None:
            # Convert any key that matches known env mapping
            for key, tag in ENV_MARKERS.items():
                if key.lower() in k.lower():
                    return tag
            return "<MISSING_SECRET>"  # fallback instead of None/null
        return v

    def recurse(obj):
        if isinstance(obj, dict):
            return {k: recurse(clean(k, v)) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [recurse(clean("", i)) for i in obj]
        return obj

    return recurse(obj)