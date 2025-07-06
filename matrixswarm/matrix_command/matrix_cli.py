import os
import json
from datetime import datetime

# Path to Matrix's payload directory
PAYLOAD_DIR = "/sites/orbit/python/comm/matrix/payload"
OUTBOX_DIR = "/sites/orbit/python/comm/matrix/outbox"
LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)


def send_command(command_type, content):
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    filename = f"{command_type}_{timestamp}.json"
    filepath = os.path.join(PAYLOAD_DIR, filename)

    command = {
        "type": command_type,
        "timestamp": timestamp,
        "content": content
    }

    with open(filepath, 'w', encoding="utf-8") as f:
        json.dump(command, f, indent=2)

    log_path = os.path.join(LOG_DIR, "matrix_cli.log")
    with open(log_path, 'a', encoding="utf-8") as log:
        log.write(f"[SENT] {filename} :: {json.dumps(content)}\n")

    print(f"\n✅ Command '{command_type}' sent as {filename}\n")


def check_outbox():
    print("\n📬 MATRIX OUTBOX MESSAGES\n========================")
    if not os.path.exists(OUTBOX_DIR):
        print("[!] Outbox directory not found.")
        return

    files = sorted(os.listdir(OUTBOX_DIR), reverse=True)[:5]  # Show last 5
    for fname in files:
        fpath = os.path.join(OUTBOX_DIR, fname)
        with open(fpath, 'r', encoding="utf-8") as f:
            try:
                msg = json.load(f)
                print(f"- {fname}: {msg.get('status', 'N/A')} :: {msg.get('message', '')}")
            except:
                print(f"- {fname}: [Unreadable JSON]")


def load_json_from_file():
    fname = input("Enter path to JSON file: ").strip()
    if not os.path.exists(fname):
        print("[!] File not found.")
        return None
    try:
        with open(fname, 'r', encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Failed to load: {e}")
        return None


def main():
    print("\n🧠 MATRIX COMMAND INTERFACE v2.0 🧠")
    print("Type a command:")
    print("  spawn | kill | inject | delete_node | delete_subtree | show_outbox | quit")

    while True:
        user_input = input("MATRIX > ").strip()

        if user_input == "quit":
            print("\n👋 Exiting CLI. Matrix remains vigilant.")
            break

        elif user_input in ["spawn", "kill", "inject", "delete_node", "delete_subtree"]:
            data = load_json_from_file()
            if data:
                send_command(user_input, data)

        elif user_input == "show_outbox":
            check_outbox()

        else:
            print("Unknown command. Try again.")


if __name__ == "__main__":
    main()

