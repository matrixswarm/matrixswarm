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
- `/comm` → communication; enhance performance mount as tmpfs mem-disk


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
