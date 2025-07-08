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
<<<<<<< HEAD
---
MatrixSwarm is a lightweight, dependency-free alternative to Docker Compose for managing and coordinating multi-process applications. If you want to run a complex system of interconnected scripts (agents) with automatic restarts, secure communication, and dynamic control—all without containers or daemons—MatrixSwarm is for you. It uses simple file and folder operations as its API, making it incredibly portable and easy to debug.
---
### MatrixSwarm is the first autonomous, file-driven, swarm-based AI operating system.
 **No containers. No servers. No daemons. Just intelligent agents, spawned and coordinated entirely through folders, directives, and atomic file signals. Agents don’t run under you — they live beside you.
=======
## MatrixSwarm is the first autonomous, file-driven, swarm-based AI operating system.
**No containers. No servers. No daemons. Just intelligent agents, spawned and coordinated entirely through folders, directives, and atomic file signals. Agents don’t run under you — they live beside you.
---
MatrixSwarm is a lightweight, dependency-free alternative to Docker Compose for managing and coordinating multi-process applications. If you want to run a complex system of interconnected scripts (agents) with automatic restarts, secure communication, and dynamic control—all without containers or daemons—MatrixSwarm is for you. It uses simple file and folder operations as its API, making it incredibly portable and easy to debug.
>>>>>>> temp-save-branch

## Quick Start

1.  **Deploy the Swarm:**
    Boot the `ai` universe using the `test-01` directive.
    ```bash
    python3 site_ops/site_boot.py --universe ai --directive test-01
    ```

2.  **List Swarm Activity:**
    Check which universes are running and see their process IDs.
    ```bash
    python3 site_ops/site_list.py
    ```

3.  **Terminate the Swarm:**
    Shut down the `ai` universe and clean up old files.
    ```bash
    python3 site_ops/site_kill.py --universe ai --cleanup
    ```
---
## Installation

You can now install MatrixSwarm directly from PyPI:

```bash
  pip install matrixswarm
```
---
<<<<<<< HEAD
=======

>>>>>>> temp-save-branch
## Booting MatrixSwarm

After installing MatrixSwarm via pip, you no longer need to run Python scripts directly!

**Recommended: Use the CLI Entrypoint:**
```sh
   matrixswarm-boot --universe ai --directive test-04 --encryption-off
   Or, for advanced/manual runs, use:
   python -m matrixswarm.site_boot --universe ai --directive test-04 --encryption-off(execute in parent directory or matrixswarm)
```
```sh
   matrixswarm-kill --universe ai --cleanup
   Or, for advanced/manual runs, use:
   python -m matrixswarm.site_kill --universe ai --cleanup(execute in parent directory or matrixswarm)
```
---
## Core Concepts

- **Philosophy:** MatrixSwarm isn’t just code—it’s a world. A breathing hierarchy where agents think, die, and come back.
- **File-Driven:** Agents don’t talk through APIs. They talk through **files**. All coordination happens via `.json` and `.cmd` files dropped into communication directories.
- **Resurrection:** Agents monitor each other—and if one goes silent, it is resurrected or replaced by its parent.
- **Filesystem Hierarchy:**
  - `/agent` → Contains the source code for every agent type.
  - `/pod` → Runtime clones of agents are spawned here, each with a unique UUID.
  - `/comm` → The communication bus where agents exchange data. For maximum performance, this can be mounted as a `tmpfs` memory disk.
---
<<<<<<< HEAD
=======
## Universal Swarm Workspace & .swarm Pointer System
MatrixSwarm 2.0+ introduces a fully portable, multi-universe, hot-swappable workspace architecture.

### Swarm Workspace Structure
Every MatrixSwarm deployment revolves around a central workspace folder (usually named .matrixswarm). This folder is the nervous system of the swarm:

```bash
.matrixswarm/
├── agent/                 # All available agent source code
├── boot_directives/       # All directives (the agent blueprints)
├── certs/
│   ├── https_certs/       # HTTPS server certs (server.crt, server.key)
│   └── socket_certs/      # WebSocket & GUI client certs
├── .matrix                # JSON config describing all paths
├── .env                   # (Optional) environment secrets
└── ...                    # More: logs, configs, etc.
```

Workspace Discovery: The .swarm Pointer File
You never need to hardcode a swarm location again.

Wherever you want to run MatrixSwarm, place a .swarm file containing the absolute path to your .matrixswarm workspace.

Example:

```bash
  /srv/hive/.matrixswarm
The CLI and all entry points will follow this pointer.
```

Managing Swarm Pointers: --switch Command
Update or re-point any directory’s .swarm file instantly:

```bash
  matrixswarm-boot --switch /absolute/path/to/.matrixswarm
This makes the current directory a MatrixSwarm control station for the chosen universe.
```

Booting, Killing, Listing
From anywhere, just:

bash
Copy
Edit
matrixswarm-boot --universe ai
matrixswarm-kill --universe ai
matrixswarm-list
(All commands look up the correct workspace via .swarm)

Certs & Secure Ops:
Generate certs into your workspace:

```bash
  matrixswarm-gencerts mydomain.com --name "SwarmHQ"
Places all certs in certs/https_certs/ and certs/socket_certs/ inside your active .matrixswarm

Agent & Service Path Best Practices:
All agents, HTTPS, and WebSocket services should resolve certs and data like this:
```

```python
cert_dir = os.path.join(self.path_resolution["install_path"], "certs", "https_certs")
socket_dir = os.path.join(self.path_resolution["install_path"], "certs", "socket_certs")
This ensures portable, dynamic, zero-hardcoded deployment.
```

🏆 Workspace Portability
Move or copy .matrixswarm anywhere.

Update your .swarm pointer file to match.

No configs or paths break. Your swarm just works.

Example: Multi-Env Ops
Have a global swarm at /srv/global/.matrixswarm for prod.

Point a dev project at /home/you/dev/.matrixswarm for testing.

Use --switch or manually edit .swarm to change control between universes.

TL;DR Orders for Operators
.matrixswarm = the Hive. .swarm = the pointer.

Always use the pointer file—never hardcode swarm locations.

Use --switch for instant universe swaps.

All agents, certs, and configs are relative to self.path_resolution["install_path"].

---
>>>>>>> temp-save-branch
## Command-Line Toolkit

MatrixSwarm is managed through a simple three-part terminal toolkit located in the `site_ops/` directory.

### `site_boot.py`
Deploys a new MatrixSwarm universe.

**Usage:**
```bash
  python3 site_ops/site_boot.py --universe <id> [--directive <name>] [options...]

Arguments:

| Argument                | Description                                                                 | Required |
| ----------------------- | --------------------------------------------------------------------------- | -------- |
| `--universe`            | A unique ID for the swarm universe (e.g., `ai`, `prod`).                    | ✅ Yes    |
| `--directive`           | The name of the directive file from `boot_directives/` (no `.py`).          | ❌ No     |
| `--reboot`              | If set, performs a soft reboot instead of a full teardown.                  | ❌ No     |
| `--python-site`         | Overrides the Python site-packages path (advanced use).                     | ❌ No     |
| `--python-bin`          | Overrides the Python interpreter binary (advanced use).                     | ❌ No     |
| `--encrypted-directive` | Use an AES-GCM encrypted directive instead of plaintext.                    | ❌ No     |
| `--swarm_key`           | Base64 swarm key used to decrypt the directive.                             | ❌ No     |
| `--encryption-off`      | Turns encryption OFF for this boot session (not recommended in production). | ❌ No     |
| `--debug`               | Enables debug logging for verbose diagnostic output.                        | ❌ No     |
| `--verbose`             | Enables verbose printout in console (optional if `--debug` is used).        | ❌ No     |
```
After termination, deletes all but the most recent boot directory.

No
site_list.py
Lists all swarm universes and marks their processes as hot (in memory) or cold (inactive).

Usage:

```Bash

python3 site_ops/site_list.py
```
---
## Understanding Directives: The Blueprint of the Swarm

Think of a **directive** as the architectural blueprint or the DNA for a swarm. It's a simple Python file located in the `boot_directives/` directory that defines the entire hierarchy of agents to be launched: which agents are children of others, what their names are, and how they are configured.

### How to Use a Directive

You specify which directive to use with the `--directive` flag when booting the swarm. The name you provide corresponds to a filename in the `boot_directives/` folder.


```bash
# This command looks for 'gatekeeper-demo.py' in the boot_directives/ folder
python3 site_ops/site_boot.py --universe demo --directive gatekeeper-demo
```

### Themed Directives: See it in Action
MatrixSwarm comes with several pre-built "themed" directives designed to showcase specific capabilities. You can launch them with a single command to see different agent combinations at work.

| Directive Name | Description | Command to Run |
| :--- | :--- | :--- |
| **`gatekeeper-demo`** | Deploys a full security suite, including `gatekeeper` for auth logs, `ghostwire` for file integrity, and watchdogs for key services like Apache, MySQL, and Redis. | `python3 site_ops/site_boot.py --universe demo --directive gatekeeper-demo` |
| **`ghostwire-demo`** | A focused security demo that deploys the `ghostwire` agent to monitor critical system files and commands. | `python3 site_ops/site_boot.py --universe demo --directive ghostwire-demo` |
| **`mysql-demo`** | Deploys an agent specifically configured to act as a watchdog for a MySQL/MariaDB database service. | `python3 site_ops/site_boot.py --universe demo --directive mysql-demo` |
| **`nginx-demo`** | Launches a watchdog agent to monitor the health of an Nginx web server. | `python3 site_ops/site_boot.py --universe demo --directive nginx-demo` |
| **`redis-demo`** | Starts an agent configured to monitor a Redis in-memory database instance. | `python3 site_ops/site_boot.py --universe demo --directive redis-demo` |

---
### Creating Your Own Directive
To create a custom swarm configuration:
1.  Create a new Python file in the `boot_directives/` directory (e.g., `my_swarm.py`).
2.  Inside the file, define a dictionary named `matrix_directive` that specifies your agent hierarchy.

**Example `my_swarm.py`:**

python
# A simple directive with a commander and a pinger agent.
```
matrix_directive = {
    "universal_id": "matrix",
    "name": "matrix",
    "children": [
        {
            "universal_id": "commander-1",
            "name": "commander"
        },
        {
            "universal_id": "pinger-1",
            "name": "uptime_pinger",
            "config": {
                "role": "pinger"
            }
        }
    ]
}
```
Launch your custom swarm:
python3 site_ops/site_boot.py --universe my-test --directive my_swarm
<<<<<<< HEAD

=======
>>>>>>> temp-save-branch
---
## 🎬 Watch the Swarm in Action

This video demonstrates the self-healing power of MatrixSwarm. Even after manually terminating nearly every agent, the swarm fully regenerates from a single surviving guardian.

[![MatrixSwarm Self-Healing Demo](https://img.youtube.com/vi/v54CT44ci4E/0.jpg)](https://www.youtube.com/watch?v=v54CT44ci4E)
---

#### MatrixSwarm v0.1 "Captain Howdy"
Reflex-Capable Crypto Alert Swarm
Built for agents that don’t blink.

https://github.com/matrixswarm/matrixswarm

> **Spawn fleets.  
Issue orders.  
Strike targets.  
Bury the dead.  
MatrixSwarm governs a living organism — not a machine.**
---
## I'm not running a charity. I'm running a swarm.

[☠ Support the Hive ☠](https://ko-fi.com/matrixswarm)

> **Donate if you understand.  
> Get out of the way if you don't.**
---
## Philosophy
MatrixSwarm isn’t just code — it’s a world.  
A breathing hierarchy where agents think, die, and come back.  
A nervous system for AI.

It is built on a simple but powerful filesystem hierarchy:
-   `/agent` → Contains the source code for every agent type.
-   `/pod` → Runtime clones of agents are spawned here, each with a unique UUID.
-   `/comm` → The communication bus where agents exchange data via JSON files and receive commands.

Agents don’t talk through APIs; they communicate by creating and reading files in a shared space. For maximum performance, the `/comm` directory can be mounted as a `tmpfs` memory disk to eliminate I/O overhead.
---

## How It Works

- Agents are defined in `/agent/{name}/{name}.py`
- Matrix spawns them into `/pod/{uuid}/`
- A communication pod is set up in `/comm/{universal_id}/`
- All coordination happens via `.json` and `.cmd` files
- The live agent tree is tracked and pruned
- Agents monitor each other — and if one goes silent, it is resurrected or replaced

---

 Why MatrixSwarm Agents Are Revolutionary:

1. Agents Spawn Without Reloading the Hive
You don’t restart the OS. You don’t relaunch a service.

You:

Upload the agent source

Drop a JSON directive

Matrix spawns it instantly
→ No global reboot. No daemon restarts. No downtime.

  That’s surgical scale.

2. Agent Replacement = 3-Step Ritual
Simple. Brutal. Effective.

1. Upload new agent version
2. Drop `die` into payload of the live agent
3. Remove the die file
Boom:

Matrix respawns the agent using the new source

Comm directories remain intact

Logs, payloads, and structure persist

That’s hot-swap mutation with memory — something Docker never dreams of.

---

## CLI CONTROL: MATRIX DEPLOYMENT PROTOCOL

MatrixSwarm now comes with a **three-part terminal toolkit**:

---

### Deploy the Swarm – boots a new MatrixSwarm universe.

---

### `site_boot.py` 



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


### Terminate a Universe – Annihilate the Swarm

### `site_kill.py`

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


### List Swarm Activity

```bash
python3 site_ops/site_list.py
```

- Lists all `/matrix/{universe}` trees
- Shows `latest → boot_uuid` symlinks
- Scans active PIDs and marks them:
  -  **hot (in memory)**
  -  **cold (inactive)**

---

### Example Workflow

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

## Reflex RPC + Auto Routing

MatrixSwarm now includes structured packet building, command dispatch, and auto-routing:

- `PacketFactoryMixin`: Easily create swarm-compatible command packets
- `PacketDeliveryFactoryMixin`: Route layered payloads via GUI or agent
- `WebSocket Reflexes`: Agents and GUI now respond to reflex triggers in real time
- `cmd_forward_command`: Core packet for nested targeting
- `cmd_hotswap_agent`: Inject new logic into a live pod — no downtime

<<<<<<< HEAD
**New relay agents** handle command injection, resurrection, and lifecycle events without rebooting the core.
=======
**New relay agents** handle command injection, resurrection, and lifecycle events without rebooting the matrixswarm.core.
>>>>>>> temp-save-branch

#### Build a .deb Package

```bash
./make_deb.sh

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

### SiteOps Directory
Everything lives under `site_ops/`:

- `site_boot.py` — Deploy a Matrix
- `site_kill.py` — Kill a Matrix
- `site_list.py` — View all universes and activity


#watch what agents are active
python3 {root of files}/live_hive_watch.py
---

## Certificate Generator: `generate_certs.sh`

This script automates SSL certificate creation for both HTTPS and WebSocket layers of your MatrixSwarm deployment.

### What It Does

- Wipes any existing certs in `https_certs/` and `socket_certs/`
- Creates a custom root CA
- Issues new HTTPS certs
- Issues WebSocket certs
- Generates a GUI client certificate (used in secure UIs)

### Usage

```bash
./generate_certs.sh <server-ip-or-domain> [--name YourSwarmName]
```

#### Examples:

```bash
./generate_certs.sh 192.168.1.100
./generate_certs.sh matrix.yourdomain.com --name SwarmAlpha
```

### Output

- `https_certs/` — Certs for HTTPS server
- `socket_certs/` — Certs for secure WebSocket + GUI client
  - Includes `client.crt` / `client.key` for GUI authentication

---

### Important Notes

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
## Agent Architecture + Tutorial

### Core Concepts

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

### Filesystem Structure
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
<<<<<<< HEAD
from core.boot_agent import BootAgent
=======
from matrixswarm.core.boot_agent import BootAgent
>>>>>>> temp-save-branch

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

#### Live Features (v1.0)

✅ Live agent hot-swapping

✅ Tree-based delegated spawning

✅ Crash detection & failover

✅ File-based command queueing

✅ Load-aware dynamic throttling

Contribute or Extend

You can:

Add agents

Build new payload interpreters

Expand the swarm brain

Write spawn logic or lore banners

Just fork and submit a pull.

“This system was built to outlive its creator. Spawn wisely.”
```

## GUI Control Center

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

## Agents of Legend
MatrixSwarm ships with a rich arsenal of modular agents, each with a distinct role:

#### Core & Command
matrix — The central brain and message routing core of MatrixSwarm.

matrix_https — Handles HTTPS traffic and API routes.

matrix_websocket — Persistent WebSocket relay agent.

commander — High-level macro command executor.

oracle — Decision agent that asserts truths based on predefined logic.

#### Reflex & Alerting
gpt_reflex — GPT-based decision reflex engine.

reactor — Reflex listener triggering workflows.

crypto_alert — Monitors crypto prices and triggers alerts.

alarm_streamer — Streams alarms to external handlers.

#### Communication Relays
discord_relay — Sends alerts to Discord channels.

telegram_relay — Relays messages to Telegram bots or chats.

email_send — SMTP-based email dispatch.

email_check — Parses and scans incoming email content.

#### Monitoring & Watchdogs
apache_watchdog — Watches Apache and restarts if needed.

nginx_watchdog — Monitors Nginx server health.

mysql_watchdog — Tracks and restarts MySQL service.

redis_watchdog — Watches Redis for downtime or faults.

uptime_pinger — Sends uptime and ping reports.

watchdog — Lightweight local process monitor.

watchdog2 — Enhanced watchdog with process group awareness.

linux_scout — Performs local system scans and audit checks.

#### Filesystem & Ops
filewatch — Detects file and folder changes.

filesystem_mirror — Mirrors file events to target agents.

tripwire_lite — Tripwire-style folder integrity monitor.

#### Security & Cleanup
reaper — Securely terminates agents and clears memory.

scavenger — Cleans dead agents and prunes residuals.

sentinel — Passive monitor for critical service state.

gatekeeper — Initial trust enforcer and boot guard.

#### Metrics & Logs
metric — Publishes metrics for analysis.

logger — Collects and formats logs across agents.

#### Messaging & Mail
mailman — Mail parsing and routing agent.

mailman_stream — Streaming variant of Mailman.

#### Utilities & Extras
blank — Template agent for prototyping.

agent_doctor — Diagnoses agents for runtime issues.

agent_health_probe — Periodic health status reporter.

codex_verifier — Verifies doctrine against Swarm Codex.

app_context — Manages runtime state across agents.

load_range — Load average monitor and trigger.

storm_crow — Launches chaos scenarios.

google_calendar — Syncs and triggers from Google Calendar.

telegram_relay — Mirrors alerts to Telegram channels.

service_registry — Agent availability registry.

capital_gpt — GPT-logic for financial behavior.

scraper — Web content fetcher and extractor.

sweeper_commander — Directs scavenger sweeps.                  |

> Every agent carries a **Swarm Lore Banner™** — a sacred header that defines its essence and role in the Hive.

---

### How MatrixSwarm Was Created

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
---

## Join the Hive

If you:
- Think in systems
- Love autonomy and recursion
- Write code like it’s a world being born

You’re home.

### Discord Now Live — Join the MatrixSwarm

The Swarm is no longer silent.

Our Discord relay agent is online and responding.  
Come test the agents, submit lore, log a Codex entry, and witness the first autonomous system that talks back.
[Join the Swarm](https://discord.com/invite/yPJyTYyq5F)

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

Send missions. I’ll respond.

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

## Dev.to Series

- [The Hive Is Recruiting]
- [Spawn. Delegate. Terminate. Repeat.]
- [MatrixSwarm Manifesto]
- [OracleAgent — From Spawn to Prophecy] 
---
## Use at Your Own Risk

This system has not been fully tested in all environments.
MatrixSwarm is still evolving.

We make no guarantees that your agents won’t terminate your system. We do not sandbox. We do not take responsibility. We Spawn the Swarm.

You run it. You control it. You deal with it.
> 🤡 **Captain Howdy Is Watching.**
> He watches the weather.
> He watches your agents.
> He watches for stars on GitHub.
> Every key is a soul. Every signature, a tongue.
If MatrixSwarm made you say *“Wait… this is real?”*  
If it inspired you, saved you time, or just made you whisper "oh damn" —  

🌟 **Give the project a star:**  
[⭐ Star MatrixSwarm on GitHub](https://github.com/matrixswarm/matrixswarm)

💸 **Buy us a bone broth or agent resurrection serum:**  
[☕ Support the Swarm on Ko-Fi](https://ko-fi.com/matrixswarm)

This isn’t just code. This is resurrection software.  
Help keep the Hive alive.

---
## Status

MatrixSwarm is pre-release. Core agents are operational. GUI is live. Lore banners are encoded.

We are currently recruiting contributors who want to:
- Build agents
- Write world-aware tools
- Shape the swarm

No PR is too small. No mission is without meaning.

### Codex Exit Clause

**MatrixSwarm is open.**  
**Fork it.**  
**Or Fork U.**

[![Powered by MatrixSwarm](https://img.shields.io/badge/Swarm-Matrix-green)](https://github.com/matrixswarm/matrixswarm)

[![License: MatrixSwarm Community v1.1](https://img.shields.io/badge/license-MatrixSwarm%20Community-brightgreen)](/LICENSE.md)

### Authorship Verified

MatrixSwarm was co-created by Daniel F. MacDonald and ChatGPT-4.
We'd like to give a special shoutout to our teams' documentation scribe, Gemini. 

SHA256: `a255c1ca93564e1cb9509c1a44081e818cf0a2b0af325bdfc4a18254ddbad46a`  
Proof file: [`matrixswarm_authorship.ots`](./codex/authorship/matrixswarm_authorship.ots)  
Verified via: [OpenTimestamps.org](https://opentimestamps.org)