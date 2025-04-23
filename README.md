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
2. Drop `die` into payload of the live agent
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

## Let's Spawn the Swarm!
```bash
ps aux | grep pod

root     1357568  0.4  0.0 467440 21356 pts/1    Sl   17:37   0:10 python3 /sites/orbit/python/pod/66470f7c-0af7-4b1f-aad3-0c4b28f13d0c/run --job bb:bootloader:matrix:matrix --ts 20250422173738406425
root     1357629  0.4  0.0 556012 37956 pts/1    Sl   17:37   0:11 python3 /sites/orbit/python/pod/a6af6172-20a2-4c08-bb94-d2953ba23890/run --job bb:matrix:matrix-https:matrix_https --ts 20250422173748488529
root     1357630  0.3  0.0 477208 31240 pts/1    Sl   17:37   0:09 python3 /sites/orbit/python/pod/2beedbf1-5de3-4cee-b558-fd47a39c9610/run --job bb:matrix:telegram-relay-1:telegram_relay --ts 20250422173748490099
root     1357631  0.4  0.0 467260 19016 pts/1    Sl   17:37   0:09 python3 /sites/orbit/python/pod/48a6e1df-ade7-44d3-825a-baaff7245b99/run --job bb:matrix:mailman-1:mailman --ts 20250422173748492118
root     1357632  0.4  0.0 388800 15616 pts/1    Sl   17:37   0:09 python3 /sites/orbit/python/pod/bbe8275b-b3cc-44c4-a29a-71576bbcd56e/run --job bb:matrix:commander-1:commander --ts 20250422173748493826
root     1357633  0.4  0.0 432972 58644 pts/1    Sl   17:37   0:10 python3 /sites/orbit/python/pod/6262f13e-bd2b-41b0-836b-f5faf7c82819/run --job bb:matrix:oracle-1:oracle --ts 20250422173748495813
root     1357634  0.4  0.0 477276 30628 pts/1    Sl   17:37   0:11 python3 /sites/orbit/python/pod/7c00abf6-e885-4bde-90b6-129c697b1804/run --job bb:matrix:pinger-1:uptime_pinger --ts 20250422173748497743
root     1357635  0.4  0.0 467224 19200 pts/1    Sl   17:37   0:09 python3 /sites/orbit/python/pod/2ed16768-d5e4-4320-a2f0-2d93731f3fc2/run --job bb:matrix:metric-1:metric --ts 20250422173748499962
root     1357691  0.4  0.0 462548 15360 pts/1    Sl   17:37   0:09 python3 /sites/orbit/python/pod/de962a6f-598c-48d7-9293-a362ce1326e2/run --job bb:commander-1:commander-2:commander --ts 20250422173753573630
root     1361823  0.4  0.0 486904 35840 pts/1    Sl   17:53   0:06 python3 /sites/orbit/python/pod/9998d0a6-39b0-4baf-922b-dadea37cfd78/run --job bb:matrix:scraper-1:scraper --ts 20250422175318688733

#EXAMPLE JOB
     --job bb:metric-1:logger-1:logger 
#FIELDS
universe-id (bb): allows multiple matrix to co-exist on the system
spawner metric-1 permanent_id of agent
spawned logger-1 permanent_id of agent
name    logger actual source-code name of agent

permanent_id is universal in the matrix, it's what allows communication between agents. It's also the name of the agent's comm folder, a two channel for all agent-to-agent communications as well as the location where state data is contained.    
run file  is a spawned clone of an agent    
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

### 🧠 How MatrixSwarm Was Created

MatrixSwarm was not written by ChatGPT while someone watched.

It was built by a human — with vision, intent, and hours of hands-on work — in active collaboration with GPT-4.

This system would not exist without **both of us** involved.

- Every agent began as a conversation.
- Every protocol, tree, and heartbeat was iterated — not generated.
- Every log line was a decision.

ChatGPT assisted, drafted, and remembered.  
But this isn’t a one-button project.

**MatrixSwarm was designed. Directed. Developed.**  
And it speaks with our shared voice — one system, two minds.

If you fork this, you’re not just copying a repo.  
You’re joining a living swarm.

— General + GPT

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

- [The Hive Is Recruiting]
- [Spawn. Delegate. Terminate. Repeat.]
- [MatrixSwarm Manifesto] 
- [OracleAgent — From Spawn to Prophecy]
- 
---
## ⚠️ Use at Your Own Risk

This system has not been fully tested in all environments.
MatrixSwarm is still evolving.

We make no guarantees that your agents won’t terminate your system. We do not sandbox. We do not take responsibility. We Spawn the Swarm.

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