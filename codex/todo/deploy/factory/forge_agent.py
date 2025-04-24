import os
import uuid
import json

SITE_ROOT = "/sites/orbit/python"
TEMPLATE_PATH = os.path.join(SITE_ROOT, "deploy/factory/worker.template.py")
OUTPUT_ROOT = os.path.join(SITE_ROOT, "agent")


def forge_agent(agent_name, delegated=None):
    delegated = delegated or []
    agent_uuid = str(uuid.uuid4())
    class_name = agent_name.capitalize() + "Agent"

    try:
        with open(TEMPLATE_PATH, "r") as f:
            template_code = f.read()
    except FileNotFoundError:
        print(f"[!] Template not found at {TEMPLATE_PATH}")
        return

    final_code = template_code.replace("{{CLASS_NAME}}", class_name)
    final_code = final_code.replace("{{UUID}}", agent_uuid)
    final_code = final_code.replace("{{DELEGATED_LIST}}", json.dumps(delegated))

    agent_dir = os.path.join(OUTPUT_ROOT, agent_name)
    os.makedirs(agent_dir, exist_ok=True)
    agent_path = os.path.join(agent_dir, f"{agent_name}.py")

    with open(agent_path, "w") as f:
        f.write(final_code)

    print(f"✅ Agent '{agent_name}' created at: {agent_path}")
    print(f"   - UUID: {agent_uuid}")
    print(f"   - Delegated: {delegated}\n")


if __name__ == "__main__":
    name = input("Agent name: ").strip()
    delegated_input = input("Delegated (comma-separated): ").strip()
    delegated_list = [x.strip() for x in delegated_input.split(",") if x.strip()]
    forge_agent(name, delegated_list)
