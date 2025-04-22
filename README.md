# 🧠 MatrixSwarm

**MatrixSwarm** is a distributed, file-driven agent operating system.  
**Spawn the Swarm.**

No containers. No daemons. No sockets. Just purpose-built swarms running on real files.

Spawn agents. Delegate missions. Kill subtrees. Resurrect the dead.

This isn't just some vibe-driven science project. Okay, maybe a *little* — but what we had before was **serious infrastructure**:
- Redis-backed socket mesh
- TLS messaging framework
- Full daemon lifecycle hooks

Then it got nuked. And what rose from the ashes is faster, leaner, and way more brutal.

---

## ⚔️ Philosophy

MatrixSwarm isn’t just code — it’s a world.  
A breathing hierarchy where agents think, die, and come back.  
A nervous system for AI.

It uses simple folders:
- `/agent` → source code
- `/pod` → runtime clones
- `/comm` → communication (dropzone for payload, status, logs)  
  ↪ *Pro tip: mount this as a `tmpfs` mem-disk for swarm speed and zero I/O overhead.*

Agents don’t talk through APIs. They talk through **files**.

---

## 🔧 How It Works

- Agents are defined in `/agent/{name}/{name}.py`
- Matrix spawns them into `/pod/{uuid}/`
- A communication pod is set up in `/comm/{permanent_id}/`
- All coordination happens via `.json` and `.cmd` files
- The live agent tree is tracked and pruned
- Agents monitor each other — and if one goes silent, it is resurrected or replaced

---

🧠 Why MatrixSwarm Agents Are Revolutionary:

1. Agents Spawn Without Reloading the Hive
You don’t restart the OS. You don’t relaunch a service.

You:

Upload the agent source

Drop a JSON directive

Matrix spawns it instantly
→ No global reboot. No daemon restarts. No downtime.

🧬 That’s surgical scale.

2. Agent Replacement = 3-Step Ritual
Simple. Brutal. Effective.

text
Copy
Edit
1. Upload new agent version
2. Drop `die.json` into payload of the live agent
3. Remove the die file
Boom:

Matrix respawns the agent using the new source

Comm directories remain intact

Logs, payloads, and structure persist

🧠 That’s hot-swap mutation with memory — something Docker never dreams of.

## 🚀 How to Boot the Swarm (Initial Boot)

```bash
git clone https://github.com/matrixswarm/matrixswarm.git
cd matrixswarm
python3 bootloader.py
```

## Let Spawn the Swarm!
```bash
ps aux | grep pod

#EXAMPLE
     --job bb:metric-1:logger-1:logger 
#FIELDS
universe-id (bb): allows multiple matrix to co-exist on the system
spawner metric-1 permanent_id of agent
spawned logger-1 permanent_id of agent
name    logger actual source-code name of agent

permanent_id is universal in the matrix, it's what allows communication between agents    
    
```

On first boot:
- MatrixAgent initializes
- Sentinel, Commander, and all core agents are spawned
- The live swarm tree appears
- Logs start flowing into `/comm/`

---

## 💻 GUI Control Center

Use the MatrixSwarm GUI to:
- Inject agents
- Kill agents or whole subtrees
- Resume fallen agents
- Deploy full mission teams
- View logs in real time

Launch the GUI:
```bash
python3 gui/matrix_gui.py
```

---

## 📦 Agents of Legend

| Agent           | Role                                     |
|----------------|------------------------------------------|
| 🧠 MatrixAgent     | Central cortex, receives all commands     |
| ☠ ReaperAgent      | Kills processes, wipes runtime clean      |
| 🧹 ScavengerAgent  | Cleans pods, removes orphaned dirs        |
| 🛡 SentinelAgent   | Watches heartbeats and resurrects agents |
| 📬 MailmanAgent    | Logs messages and deduplicates hash lines |
| 🔮 OracleAgent     | AI responder that interprets `.prompt` files using GPT-4 |

Each agent carries a **Swarm Lore Banner™** — a sacred header that defines its purpose.

---

## 🧬 Join the Hive

If you:
- Think in systems
- Love autonomy and recursion
- Write code like it’s a world being born

You’re home.

Read `CONTRIBUTING.md`, clone the repo, and pick a mission.

```bash
git clone https://github.com/matrixswarm/matrixswarm.git
cd matrixswarm
python3 bootloader.py
```

---

## 📖 Dev.to Series

- [The Hive Is Recruiting](https://dev.to/your-post)
- [Spawn. Delegate. Terminate. Repeat.](https://dev.to/your-post)
- [MatrixSwarm Manifesto (coming soon)](https://dev.to/your-post)
- [OracleAgent — From Spawn to Prophecy (coming soon)](https://dev.to/your-post)

---
## ⚠️ Use at Your Own Risk

This system has not been fully tested in all environments.
MatrixSwarm is still evolving.

We make no guarantees that your agents won’t terminate your system.We do not sandbox.We do not take responsibility.We Spawn the Swarm.

You run it. You control it. You deal with it.

---
## 🛡 Status

MatrixSwarm is pre-release. Core agents are operational. GUI is live. Lore banners are encoded.

We are currently recruiting contributors who want to:
- Build agents
- Write world-aware tools
- Shape the swarm

No PR is too small. No mission is without meaning.

🧠⚔️

### 🧬 Codex Exit Clause

**MatrixSwarm is open.**  
**Fork it.**  
**Or Fork U.**