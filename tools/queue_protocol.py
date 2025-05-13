#!/usr/bin/env python3
import os
import time
import shutil
from pathlib import Path

COMM_PATH = "/matrix/ai/latest/comm"
QUEUE_DIRS = ["pending", "processing", "complete", "failed"]
AGENT_TARGET = None

def ensure_queue_dirs(agent_id):
    base = os.path.join(COMM_PATH, agent_id, "queue")
    os.makedirs(base, exist_ok=True)
    for d in QUEUE_DIRS:
        os.makedirs(os.path.join(base, d), exist_ok=True)
    return base

def scan_queue(agent_id):
    base = ensure_queue_dirs(agent_id)
    print(f"🧠 Swarm Queue Report for: {agent_id}")
    for d in QUEUE_DIRS:
        path = os.path.join(base, d)
        files = os.listdir(path)
        print(f"  • {d:<10}: {len(files)} message(s)")
    print("-" * 40)

def list_agents():
    return [f for f in os.listdir(COMM_PATH) if Path(os.path.join(COMM_PATH, f, "queue")).exists()]

def run():
    print("📦 MatrixSwarm Queue Protocol Audit")
    agents = list_agents()
    for agent in sorted(agents):
        scan_queue(agent)

if __name__ == "__main__":
    run()
