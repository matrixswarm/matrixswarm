import os
import json

AGENT_DIR = "/sites/orbit/python/agent"


def scan_agents():
    registry = {}

    for agent_name in os.listdir(AGENT_DIR):
        agent_path = os.path.join(AGENT_DIR, agent_name)
        if not os.path.isdir(agent_path):
            continue

        for file in os.listdir(agent_path):
            if file.endswith(".py"):
                file_path = os.path.join(agent_path, file)
                registry[agent_name] = {
                    "path": file_path,
                    "files": [file for file in os.listdir(agent_path) if file.endswith(".py")]
                }

    return registry


def save_registry(registry):
    output_path = os.path.join(AGENT_DIR, "agent_registry.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    print(f"\n✅ Registry saved to: {output_path}\n")


def main():
    print("\n📚 AGENT INVENTORY SCAN\n========================")
    registry = scan_agents()
    for agent, info in registry.items():
        print(f"- {agent}: {info['files']}")
    save_registry(registry)


if __name__ == "__main__":
    main()
