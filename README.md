# **MATRIXSWARM**  
<pre>
███████╗██╗    ██╗ █████╗ ██████╗ ███╗   ███╗
██╔════╝██║    ██║██╔══██╗██╔══██╗████╗ ████║
███████╗██║ █╗ ██║███████║██████╔╝██╔████╔██║
╚════██║██║███╗██║██╔══██║██╔═══╝ ██║╚██╔╝██║
███████║╚███╔███╔╝██║  ██║██║     ██║ ╚═╝ ██║
╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝     ╚═╝     ╚═╝
         MATRIXSWARM v0.2 "STORMCROW"
        Reflex. Resurrection. Real-time RPC.
</pre>
## MatrixSwarm is the first autonomous, file-driven, swarm-based AI operating system.  
## No containers. No servers. No daemons. Just intelligent agents, spawned and coordinated entirely through folders, directives, and atomic file signals. Agents don’t run under you — they live beside you.

✅ No containers.  
✅ No servers.  
✅ No sockets.  

MatrixSwarm v0.1 "Captain Howdy"
Reflex-Capable Crypto Alert Swarm
Built for agents that don’t blink.

Reflex logic
Live agent patching
Directional price triggers
CLI + GUI + container support
Comes with its own warning siren

https://github.com/matrixswarm/matrixswarm

> **Spawn fleets.  
Issue orders.  
Strike targets.  
Bury the dead.  
MatrixSwarm governs a living organism — not a machine.**
---
## 💀 I'm not running a charity. I'm running a swarm.

[☠ Support the Hive ☠](https://ko-fi.com/matrixswarm)

> **Donate if you understand.  
> Get out of the way if you don't.**

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
- A communication pod is set up in `/comm/{universal_id}/`
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

That’s hot-swap mutation with memory — something Docker never dreams of.

---

## 🧠 CLI CONTROL: MATRIX DEPLOYMENT PROTOCOL

MatrixSwarm now comes with a **three-part terminal toolkit**:

---

### 🚀 Deploy the Swarm – boots a new MatrixSwarm universe.

---

### 🚀 `site_boot.py` 



```bash
python3 site_ops/site_boot.py --universe ai --directive test-01
```

#### Args:
- `--universe`: ID of the Matrix universe (e.g., `ai`, `bb`, `os`)
- `--directive`: Filename from `boot_directives/` to use (without `.py`)
- `--reboot`: Optional. If set, skips full teardown and triggers a soft reboot
- `--python-site`: Optional. Custom Python site-packages path (advanced)
- `--python-bin`: Optional. Custom Python binary path (advanced)

#### Behavior:
- Loads agent tree from the directive
- Injects `BootAgent` agents into `/pod/` and `/comm/`
- Spawns the `MatrixAgent` and initiates the swarm
- Uses your system's Python interpreter unless overridden

---


### 💀 Terminate a Universe – Annihilate the Swarm

### 💀 `site_kill.py`

Send a graceful but fatal signal to all agents in a Matrix universe.

```bash
python3 site_ops/site_kill.py --universe ai --cleanup
```

#### Args:
- `--universe`: ID of the Matrix universe to kill (required)
- `--cleanup`: Optional. After kill, delete all old `/matrix/{universe}/` boots except the latest

#### Behavior:
- Sends `die` signals into each agent’s comms
- Waits for natural shutdown
- Scans active memory to terminate leftover processes
- Optionally purges stale directories from previous boots


### 🛰 List Swarm Activity

```bash
python3 site_ops/site_list.py
```

- Lists all `/matrix/{universe}` trees
- Shows `latest → boot_uuid` symlinks
- Scans active PIDs and marks them:
  - 🔥 **hot (in memory)**
  - ❄️ **cold (inactive)**

---

### 🧬 Example Workflow

```bash
# Boot the ai universe using test directive
python3 site_ops/site_boot.py --universe ai --directive test-01

# Kill it instantly
python3 site_ops/site_kill.py --universe ai

# View which universes are active
python3 site_ops/site_list.py
```

You now have **docker-grade control** with zero containers.

---

## 📡 Reflex RPC + Auto Routing

MatrixSwarm now includes structured packet building, command dispatch, and auto-routing:

- `PacketFactoryMixin`: Easily create swarm-compatible command packets
- `PacketDeliveryFactoryMixin`: Route layered payloads via GUI or agent
- `WebSocket Reflexes`: Agents and GUI now respond to reflex triggers in real time
- `cmd_forward_command`: Core packet for nested targeting
- `cmd_hotswap_agent`: Inject new logic into a live pod — no downtime

**New relay agents** handle command injection, resurrection, and lifecycle events without rebooting the core.


### ⚡ Directives Made Easy

Every directive is a plain `.py` file:

```python
matrix_directive = {
    "universal_id": "matrix",
    "children": [
        {"universal_id": "commander-1", "name": "commander"},
        {"universal_id": "mailman-1", "name": "mailman"},
        ...
    ]
}
```

Place them in `boot_directives/`. Call them with:
```bash
--directive test-01
```

---

### 📁 SiteOps Directory

Everything lives under `site_ops/`:

- `site_boot.py` — Deploy a Matrix
- `site_kill.py` — Kill a Matrix
- `site_list.py` — View all universes and activity


#watch what agents are active
python3 {root of files}/live_hive_watch.py
---

## 🔐 Certificate Generator: `generate_certs.sh`

This script automates SSL certificate creation for both HTTPS and WebSocket layers of your MatrixSwarm deployment.

### 📦 What It Does

- Wipes any existing certs in `https_certs/` and `socket_certs/`
- Creates a custom root CA
- Issues new HTTPS certs
- Issues WebSocket certs
- Generates a GUI client certificate (used in secure UIs)

### 🧠 Usage

```bash
./generate_certs.sh <server-ip-or-domain> [--name YourSwarmName]
```

#### Examples:

```bash
./generate_certs.sh 192.168.1.100
./generate_certs.sh matrix.yourdomain.com --name SwarmAlpha
```

### 🧬 Output

- `https_certs/` — Certs for HTTPS server
- `socket_certs/` — Certs for secure WebSocket + GUI client
  - Includes `client.crt` / `client.key` for GUI authentication

---

### 🚨 Important Notes

- You must pass a **domain name or IP address** as the first argument.
- Certificates are valid for **500 days**.
- Don’t forget to distribute your `rootCA.pem` to clients that need to trust your custom CA.









## Let's Spawn the Swarm!
```bash
ps aux | grep pod

root     1127295  0.4  0.0 542124 22612 pts/1    Sl   11:14   0:04 python3 /matrix/ai/latest/pod/ec4d5a03-df5f-4562-9ebb-ead8f6fa90f8/run --job bb:site_boot:matrix:matrix --ts 20250503111458777844
root     1127322  0.4  0.0 556032 34560 pts/1    Sl   11:15   0:05 python3 /matrix/ai/20250503_111458/pod/0ef6264a-2d9f-432e-9e91-2274eef6a9ba/run --job ai:matrix:matrix-https:matrix_https --ts 20250503111503868202
root     1127323  0.4  0.0 610240 15360 pts/1    Sl   11:15   0:05 python3 /matrix/ai/20250503_111458/pod/b644220a-31f3-4469-ae88-5623f4de5aef/run --job ai:matrix:scavenger-strike:scavenger --ts 20250503111503870712
root     1127324  0.3  0.0 481436 33368 pts/1    Sl   11:15   0:04 python3 /matrix/ai/20250503_111458/pod/9bb83977-372b-4b35-bccc-7aab5a5f880d/run --job ai:matrix:telegram-relay-1:telegram_relay --ts 20250503111503873044
root     1127325  0.3  0.0 393584 19188 pts/1    Sl   11:15   0:04 python3 /matrix/ai/20250503_111458/pod/8f81b4c0-cb23-4625-93aa-2a924d199f54/run --job ai:matrix:mailman-1:mailman --ts 20250503111503875212
root     1127326  0.4  0.0 388864 15104 pts/1    Sl   11:15   0:05 python3 /matrix/ai/20250503_111458/pod/9a9a4f20-8a30-4a56-ba5f-a628b9ea532b/run --job ai:matrix:commander-1:commander --ts 20250503111503876979
root     1127327  0.4  0.0 516164 64236 pts/1    Sl   11:15   0:05 python3 /matrix/ai/20250503_111458/pod/5d9f62e1-8f01-4dc0-8352-63e67883fe18/run --job ai:matrix:oracle-1:oracle --ts 20250503111503879503
root     1127328  0.4  0.0 482464 34192 pts/1    Sl   11:15   0:05 python3 /matrix/ai/20250503_111458/pod/247023ee-59af-471e-814e-1d69f5f5d0c1/run --job ai:matrix:pinger-1:uptime_pinger --ts 20250503111503881933
root     1127329  0.3  0.0 393540 18688 pts/1    Sl   11:15   0:04 python3 /matrix/ai/20250503_111458/pod/efae5a1f-e4cf-40a9-9c8f-f531a2840a30/run --job ai:matrix:metric-1:metric --ts 20250503111503885520
root     1127330  0.4  0.0 484400 35936 pts/1    Sl   11:15   0:04 python3 /matrix/ai/20250503_111458/pod/511bfc84-57c3-4b3d-b37e-fd980683afae/run --job ai:matrix:scraper-1:scraper --ts 20250503111503888711
root     1127331  0.4  0.0 717644 47848 pts/1    Sl   11:15   0:04 python3 /matrix/ai/20250503_111458/pod/6009754c-cc50-403b-9ebe-c4fd2962d522/run --job ai:matrix:discord-relay-1:discord --ts 20250503111503892186
root     1127349  0.4  0.0 462596 17024 pts/1    Sl   11:15   0:05 python3 /matrix/ai/20250503_111458/pod/14d4e101-7b35-483b-a411-8f667c8185ef/run --job ai:commander-1:commander-2:commander --ts 20250503111503949452


#EXAMPLE JOB
     --job bb:metric-1:logger-1:logger 
#FIELDS
universe-id (bb): allows multiple matrix to co-exist on the system
spawner metric-1 universal_id of agent
spawned logger-1 universal_id of agent
name    logger actual source-code name of agent

universal_id is universal in the matrix, it's what allows communication between agents. It's also the name of the agent's comm folder, a two channel for all agent-to-agent communications as well as the location where state data is contained.    
run file  is a spawned clone of an agent    
```

On first boot:
- MatrixAgent initializes
- Sentinel, Commander, and all core agents are spawned
- The live swarm tree appears
- Logs start flowing into `/comm/`

---
## 🧠 Agent Architecture + Tutorial

### 🧩 Core Concepts

#### Worker Agents
- Inherit from `BootAgent`
- Override `worker()` to define their task loop
- Post logs and heartbeats
- Live in `/pod/{uuid}/` and communicate via `/comm/{universal_id}/`

Common examples:
- Pingers, system monitors, relay agents, loggers

#### Boot Agents
All agents extend `BootAgent`. It handles:
- Lifecycle threading (heartbeat, command, spawn)
- Dynamic throttling
- Optional pre/post hooks (`worker_pre`, `worker_post`)
- Spawn manager to detect and revive missing children

#### Aux Calls
Available to all agents:
- `spawn_manager()` → walks the tree, spawns children
- `command_listener()` → reacts to `.cmd` files
- `request_tree_slice_from_matrix()` → ask Matrix for updated subtree
- `start_dynamic_throttle()` → load-aware pacing

---

### 📁 Filesystem Structure
Each agent is deployed in two zones:

#### 1. Runtime pod:
/pod/{uuid}/
├── run (agent process)
├── log.txt
└── heartbeat.token
shell
#### 2. Communication pod:
/comm/{universal_id}/
├── payload/
├── incoming/
├── hello.moto/
└── agent_tree.json
---
### 🧪 Tutorial: Build Your First Agent

#### 1. Create the Agent Code
```python
from core.boot_agent import BootAgent

class MyAgent(BootAgent):
    def worker(self):
        self.log("I'm alive!")
        time.sleep(5)

2. Add the Directive
{
  "universal_id": "my_agent",
  "name": "MyAgent",
  "agent_path": "boot_payload/my_agent/my_agent.py",
  "children": []
}

3. Drop the Agent Code
/boot_payload/my_agent/my_agent.py

4. Deploy with Matrix
python3 reboot.py --universe demo --directive test_tree
Boom. Agent spawned. Directory structure built. Logs flowing.

🌐 Live Features (v1.0)

✅ Live agent hot-swapping

✅ Tree-based delegated spawning

✅ Crash detection & failover

✅ File-based command queueing

✅ Load-aware dynamic throttling

🛠️ Contribute or Extend

You can:

Add agents

Build new payload interpreters

Expand the swarm brain

Write spawn logic or lore banners

Just fork and submit a pull.

“This system was built to outlive its creator. Spawn wisely.”
```

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

## 🧠 Agents of Legend
| **Agent**                | **Role**                                                                                     |
|--------------------------|----------------------------------------------------------------------------------------------|
| 🧠 **MatrixAgent**        | Central cortex — receives all commands, initiates all spawns, signs the tree.               |
| 💀 **ReaperAgent**        | Executes kill orders with finality. Escalates. Terminates. Wipes runtimes clean.            |
| 🧹 **ScavengerAgent**     | Cleans abandoned pods, removes orphaned directories. Order out of chaos.                    |
| 🛡️ **SentinelAgent**      | Monitors heartbeats, confirms agent vitality, resurrects the fallen.                        |
| 📬 **MailmanAgent**       | Canonical log keeper. Deduplicates messages by hash. Streams the pulse of the Swarm.        |
| 🔮 **OracleAgent**        | AI responder that reads `.prompt` files. Thinks with GPT-4, speaks with insight.            |
| ⚡ **ReactorAgent**       | Autonomic reflex of the Swarm. Makes judgment calls. Triggers spawn chains. *(active)*      |
| 📜 **CodexViewer**        | Displays live Swarm Codex. Immortalizes agent banners and histories. *(coming soon)*        |
| 🔍 **ProcessIntelAgent**  | Monitors running processes. Tracks rogue threads and hidden anomalies. *(in dev)*           |
| 🪞 **FilesystemMirrorAgent** | Reflects and shadows file trees. Useful for surveillance, auditing, and rollback. *(online)* |
| 📣 **DiscordAgent**       | Listens to commands via Discord. Responds to `!status`, `!guest`, and relays `.msg`. *(active)* |
| 🛰️ **TelegramRelayAgent** | Sends messages from Mailman to Telegram. External voice of the Swarm. *(active)*            |
| 🧭 **UpdateSentinel**     | Watches for updates to directives, patches live agents, ensures continuity. *(deployed)*    |
| 🧹 **SweepCommander**     | Sends signals to Oracle, receives `.cmd`, executes cleanup ops. *(deployed)*                |
| 📊 **MetricsAgent**       | Tracks CPU, RAM, uptime, disk. Forwards trend data to Oracle. *(online)*                    |
| 📡 **UptimePingerAgent**  | Periodically pings sites. Broadcasts up/down status to Mailman. *(online)*                 |
| 🌐 **ScraperAgent**       | Pulls down site summaries. Parses, cleans, logs. *(online)*                                 |
| 🧬 **CodexTrackerAgent**  | Logs file downloads, external watchers, and ZIP pings. *(active)*                           |
| 📅 **CalendarAgent**      | Monitors upcoming Google Calendar events. Broadcasts timeline. *(live)*                    |
| 📁 **FileWatchAgent**     | Inotify monitor for file changes. Forwards swarm `.msg`. *(fielded)*                        |

> Every agent carries a **Swarm Lore Banner™** — a sacred header that defines its essence and role in the Hive.

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

### 🧠 Discord Now Live — Join the MatrixSwarm

The Swarm is no longer silent.

Our Discord relay agent is online and responding.  
Come test the agents, submit lore, log a Codex entry, and witness the first autonomous system that talks back.
🔗 [Join the Swarm](https://discord.com/invite/yPJyTYyq5F)

---

## 🛡 Deployment and Customization Support

MatrixSwarm isn’t just a codebase — it’s a living system.

**Custom deployments, installation support, and updates for the life of the version are available.**  
I personally assist with install tuning, advanced tree setup, large swarm deployments, and Codex expansions.

If you want your Hive operational, optimized, or expanded —  
I'm available.

Embedded below in the ancient tongue of binary is your contact path:

01110011 01110000 01100001 01110111 01101110 01000000 01101101 01100001 01110100 01110010 01101001 01111000 01110011 01110000 01100001 01110111 01101110 00101110 01100011 01101111 01101101

yaml
Copy
Edit

> **spawn@matrixspawn.com**  

💬 Send missions. I’ll respond.

---

Read `CONTRIBUTING.md`, clone the repo, and pick a mission.

```bash
git clone https://github.com/matrixswarm/matrixswarm.git
cd matrixswarm
python3 bootloader.py
```

---
## Licensing Information

MatrixSwarm is released under the **MatrixSwarm Community License v1.1 (Modified MIT)**.

This license allows you to use, modify, and distribute MatrixSwarm for **personal, academic, research, and non-commercial development purposes.**

**For any commercial use, including embedding in commercial products, offering SaaS, or providing services derived from MatrixSwarm, a separate commercial license is required.**

For commercial licensing inquiries, please contact **swarm@matrixswarm.com**.

Please read the full license text in the `LICENSE.md` file for complete details.


## 📖 Dev.to Series

- [The Hive Is Recruiting]
- [Spawn. Delegate. Terminate. Repeat.]
- [MatrixSwarm Manifesto] 
- [OracleAgent — From Spawn to Prophecy] 
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

[![Powered by MatrixSwarm](https://img.shields.io/badge/Swarm-Matrix-green)](https://github.com/matrixswarm/matrixswarm)


### 🔐 Authorship Verified

MatrixSwarm was co-created by Daniel F. MacDonald and ChatGPT-4.

SHA256: `a255c1ca93564e1cb9509c1a44081e818cf0a2b0af325bdfc4a18254ddbad46a`  
Proof file: [`matrixswarm_authorship.ots`](./codex/authorship/matrixswarm_authorship.ots)  
Verified via: [OpenTimestamps.org](https://opentimestamps.org)