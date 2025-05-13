#!/usr/bin/env python3
import os
import time
from pathlib import Path

COMM_ROOT = "/matrix/ai/latest/comm"
THREADS = ["worker", "cmd_listener", "reflex_listener"]
TIMEOUT = 3  # seconds

def send_poke(universal_id, thread_name):
    poke_path = os.path.join(COMM_ROOT, universal_id, "incoming", f"poke.{thread_name}")
    Path(poke_path).touch()

def get_beacon_mtime(universal_id, thread_name):
    path = os.path.join(COMM_ROOT, universal_id, "incoming", f"poke.{thread_name}")
    if not os.path.exists(path):
        return None
    try:
        return os.path.getmtime(path)
    except:
        return None

def scan_agent(agent):
    results = {}
    for thread in THREADS:
        send_poke(agent, thread)
    time.sleep(TIMEOUT)
    now = time.time()
    for thread in THREADS:
        ts = get_beacon_mtime(agent, thread)
        if ts:
            age = round(now - ts, 2)
            results[thread] = f"{age}s ago ✅" if age < TIMEOUT + 1 else f"{age}s ago ⚠️"
        else:
            results[thread] = "❌ No beacon found"
    return results

def list_agents():
    return [d for d in os.listdir(COMM_ROOT) if Path(os.path.join(COMM_ROOT, d, "incoming")).exists()]

def run():
    print("🧠 MatrixSwarm Reflex Audit\n")
    agents = list_agents()
    for agent in sorted(agents):
        print(f"📡 Agent: {agent}")
        results = scan_agent(agent)
        for thread, status in results.items():
            print(f"  • {thread:<16} {status}")
        print("-" * 40)

if __name__ == "__main__":
    run()
