# 📜 Swarm Codex — Agent Registration Log
# Auto-generated ledger of all agents that serve the Hive.
# This file can be programmatically updated by spawn routines or manually extended.

SWARM_CODEX = [
    {
        "perm_id": "matrix",
        "agent_name": "MatrixAgent",
        "role": "Central Cortex",
        "banner": "🧠 MATRIX AGENT",
        "spawned": "Hive Zero",
        "version": "v3.0",
        "status": "Immortal"
    },
    {
        "perm_id": "reaper-root",
        "agent_name": "ReaperAgent",
        "role": "Tactical Cleanup",
        "banner": "☠ REAPER AGENT",
        "spawned": "Halls of Matrix",
        "version": "v2.5",
        "status": "Active"
    },
    {
        "perm_id": "scavenger-root",
        "agent_name": "ScavengerAgent",
        "role": "Runtime Sweeper",
        "banner": "🧹 SCAVENGER AGENT",
        "spawned": "Blackout Protocol",
        "version": "Rev 1.8",
        "status": "Active"
    },
    {
        "perm_id": "sentinel-alpha",
        "agent_name": "SentinelAgent",
        "role": "Heartbeat Monitor",
        "banner": "🛡 SENTINEL AGENT",
        "spawned": "Zone Watch",
        "version": "v1.2",
        "status": "Active"
    },
    {
        "perm_id": "mailman-1",
        "agent_name": "MailmanAgent",
        "role": "Message Relay",
        "banner": "📬 MAILMAN AGENT",
        "spawned": "Seal 7",
        "version": "v1.0",
        "status": "Standby"
    },
    {
        "perm_id": "unknown",
        "agent_name": "GhostNode",
        "role": "Residual Process",
        "banner": "👻 UNKNOWN",
        "spawned": "???",
        "version": "???",
        "status": "Banished"
    },
    {
        "perm_id": "watchdog",
        "agent_name": "WatchdogAgent",
        "role": "Site Monitor & Uptime Enforcer",
        "banner": "🧠 WATCHDOG AGENT 🧠",
        "spawned": "Forged in the core of Hive Zero",
        "version": "v3.0",
        "status": "Operational",
        "capabilities": [
            "inject",
            "replace",
            "resume",
            "kill",
            "propagate"
        ],
        "description": "Central Cortex · Tree Dispatcher · Prime Director"
    },
    {
        "perm_id": "reaper",
        "agent_name": "ReaperAgent",
        "role": "High-Authority Cleanup Unit",
        "banner": "☠ REAPER AGENT ☠",
        "spawned": "Manual Command Only",
        "version": "v1.0",
        "status": "unregistered",
        "capabilities": ["reap", "terminate", "force_kill", "subtree_cleanup"],
        "description": "Handles escalated kill orders. Graceful first, lethal if ignored."
    }

    # Future agents will be registered here
]

def register_agent(entry):
    SWARM_CODEX.append(entry)

def get_codex():
    return SWARM_CODEX

def print_codex():
    print("\n🧠 SWARM CODEX — ACTIVE LEDGER")
    print("══════════════════════════════════════════════════")
    for agent in SWARM_CODEX:
        print(f"{agent['banner']} :: {agent['perm_id']} [{agent['role']}] — {agent['status']}")
    print("══════════════════════════════════════════════════\n")

# If run standalone, print the codex
if __name__ == "__main__":
    print_codex()
