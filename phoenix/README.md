<!-- ================= PHOENIX HEADER BLOCK ================= -->

<div align="center">

# **Phoenix Cockpit**
### *The Secure Control Plane for the MatrixSwarm Universe*
**Version:** 1.1 · **Status:** Pre-Release · **License:** MatrixSwarm Community License (Modified MIT)
---
[![Built with PyQt6](https://img.shields.io/badge/Built%20with-PyQt6%206.6+-blue.svg?style=flat-square)](#)
[![Security Verified](https://img.shields.io/badge/Security-Vault%20Locked%20%26%20SPKI%20Pinned-green.svg?style=flat-square)](#)
[![MatrixOS Core](https://img.shields.io/badge/Requires-MatrixOS%203.10+-orange.svg?style=flat-square)](https://github.com/matrixswarm/matrixos)
[![Discord Hive](https://img.shields.io/badge/Join-The%20Hive-7289da?style=flat-square&logo=discord)](https://discord.gg/CyngHqDmku)
---
### **Phoenix** is not a dashboard — it’s the *nervous system* of the swarm.  
It decrypts your vault, orchestrates universes, and issues signed commands to living agents.

- Vault-secured command chain (no vault = no ops)  
- End-to-end encrypted HTTPS / WebSocket relay  
- Real-time logs, threads, and service panels  
- Full directive builder with embedded crypto certs  
- Railgun remote installer for one-click MatrixOS deployment  

---

> “The Queen never speaks directly — Phoenix is her voice.”

**MatrixSwarm Digital Labs — Victory Always.**

</div>

<!-- ========================================================= -->

## Phoenix Cockpit

Phoenix Cockpit is the GUI control plane for MatrixOS — a secure multi-agent runtime for orchestrating autonomous services.
(from the MatrixSwarm ecosystem )

---

## 💙 Support Development

If you find **MatrixOS** or the broader **MatrixSwarm ecosystem** useful and want to support ongoing updates,  
you can buy me a coffee here:

☕ **[ko-fi.com/matrixswarm](https://ko-fi.com/matrixswarm)**

Your support helps sustain development of MatrixOS, Phoenix Cockpit, and future agent frameworks —  
funding open-source maintenance, documentation, and ecosystem growth.

- Bitcoin — bc1qasqk5xn9j7cdddmeclxddzvym2sdv7d8g3xrtz

---

#### Built with PyQt6 ≥ 6.6
#### Python ≥ 3.10 is required
#### MatrixOS https://github.com/matrixswarm/matrixos required
* Enforces vault unlock → command flow (no unlocked vault, no ops).
* Visualizes universes, deployments, agents, and their threads.
* Streams logs, status, and service responses in real time.
* Every packet verified, every heartbeat tracked.

---
https://youtu.be/hwQagK71TJc
## 🎬 Watch how to deploy a swarm using Phoenix Cockpit

This video demonstrates the self-healing power of MatrixSwarm. Even after manually terminating nearly every agent, the swarm fully regenerates from a single surviving guardian.

[![Designing a MatrixSwarm Deployment with Phoenix Cockpit](https://img.youtube.com/vi/hwQagK71TJc/maxresdefault.jpg)](https://www.youtube.com/watch?v=hwQagK71TJc)
note: this is the old cockpit design
---
## ⚡ Quick Start

### Install

```bash
  pip install -e .
```
### Unlock Vault

When Phoenix starts, you’ll see only the 🔐 UNLOCK button.
Enter your vault password — the cockpit decrypts and loads trusted deployments.
No unlock = no swarm control.

#### Connect to Deployment

Right-click a deployment → 🔌 Connect.
Agents will light up in the tree.

#### Issue Commands

* Right-click an agent → restart, replace, hotswap, or delete. note: restart and hotswap are being refactored and will be implemented shortly.
* Use control panels (logs, NPC panel, forensic panel) to issue service requests.
* All commands travel securely:

```nginx
 Phoenix → matrix_https → Matrix → Agent → WebSocket Relay → Phoenix
```

### 🌌 Example Session

matrixd list <- command on server

```bash
🌌 phoenix :: 20 agents, 907.7 MB RAM, 11.3% CPU
 └── PID 2369254 :: matrix
 └── PID 2369264 :: guardian-1
 └── PID 2369265 :: matrix-https
 └── PID 2369266 :: websocket-relay
 └── PID 2369267 :: apache_watchdog-1
 └── PID 2369271 :: mysql-red-phone
 └── PID 2369272 :: log_sentinel
 └── PID 2369274 :: invisible-man
 └── PID 2369276 :: gatekeeper
 └── PID 2369279 :: discord-delta-5
 └── PID 2369281 :: forensic-detective-1
 └── PID 2369284 :: system-health-1
 └── PID 2369286 :: network-health-1
 └── PID 2369287 :: redis-hammer
 └── PID 2369289 :: telegram-bot-father-2
 └── PID 2369291 :: golden-child-4
 └── PID 2369431 :: guardian-2
 └── PID 2369471 :: guardian-3
 └── PID 2369506 :: guardian-4
```

Phoenix shows them in tree view with live updates.
Click an agent → inspect threads, spawn count, flip-tripping alerts, and configuration.

### Creating a Deployment Directive in Phoenix

1. **Start from a Template**
   Load a directive skeleton in Directive Manager (guardian ring, relays, watchdogs).

2. **Assign Connections**
   Use Connection Manager to map saved endpoints (HTTPS, WSS, Discord, Telegram, etc.).

3. **Select Options**

   * **Clown-car** (embed sources in directive) → hidden by default.
   * **Hashbang** (SHA256 hash per agent, verified on spawn) → optional.

4. **Encrypt and Save**

   "universe" is whatever you call your swarm(cluster of agents) at boot.

   Phoenix encrypts your directive into:
   `matrix/boot_directives/<universe>.enc.json`

5. **Swarm Key**
   Phoenix also saves the matching swarm key:
   `matrix/boot_directives/keys/<universe>.key`
   *Same name as directive, minus `.enc.json`.*

6. **Boot the Swarm**
   Run:

```bash
  matrixd boot --universe phoenix
```
Matrix auto-resolves the directive + key, decrypts in memory, and spawns the agents slice by slice.

---
## Railgun Install (MatrixOS Installer)

Phoenix Cockpit now includes a one-click remote installer for MatrixOS.

This feature lets you deploy MatrixOS onto any remote Linux server without SSH terminals, Putty, or manual setup.

You’ll find it in the top chrome:

⚡ Railgun ▾
   → Install MatrixOS…
   → Check Remote Host…
   → Reinstall / Overwrite…

### Railgun → Install MatrixOS

This dialog lets you push a full MatrixOS installation to any SSH-reachable server.

1. Choose a Source

You can install MatrixOS in three ways:

• Use Local MatrixOS Folder
– Select your local matrixos/ project directory.
– Phoenix bundles only the required install manifest (agents/, core/, scripts/, requirements.txt).

• Download From GitHub (Stable Release)
– Phoenix fetches the latest published MatrixOS release ZIP.

• Download From GitHub (Dev Branch)
– Pulls directly from matrixos:main.

• Custom GitHub Branch
– Enter any branch name.

No Python or Git required on your local machine.

### 2. Select SSH Target

Railgun uses your vault-stored SSH identities — Under "Connection Manager", which you define first
no passwords, no keys on disk, no manual SSH.

Select any saved connection:

myserver-1 (192.168.1.20)
myserver-1 (192.168.1.21)
myserver-1 (192.168.1.22)

Vault controls everything:

host

username

port

private key

identity label

This is the same identity system Phoenix uses for deploying directives, now used for OS installs.

### 3. Choose Install Path

Default:

/matrix


Phoenix will create:

/matrix/
    agents/
    core/
    scripts/
    boot_directives/
    boot_directives/keys/
    requirements.txt
    venv/


Check the box to overwrite an existing installation:

☑ Overwrite existing installation

### 4. Fire Railgun

Click:

⚡ Install MatrixOS

Phoenix will:

Bundle or download MatrixOS

Upload to remote server

Upload installer script

Create the install directory

Extract the manifest

Create a Python venv

Install requirements

Initialize boot_directives/

Install clean /matrix tree

Stream logs in real time

You can watch everything live in the black console pane.

No Putty.
No SSH shell.
No copying files.
No typing commands.
Just fire.

### Railgun → Check Remote Host

This tool performs a full pre-flight check before install:

SSH reachability

OS type (Rocky/Alma/CentOS/Ubuntu/Debian)

Python3 presence

pip / venv availability

/matrix existence

disk space

system time sanity

existing MatrixOS detection

This helps you diagnose remote hosts before installation.

### Railgun → Reinstall / Overwrite

Runs the same installer but forcibly:

wipes the install directory

reinstalls all MatrixOS files

rebuilds Python venv

Useful when:

upgrading MatrixOS

switching branches

resetting a corrupted system

deploying to a new clean base

### Security Behavior

All SSH keys retrieved from the vault (never written to disk).

Installer bundle streamed over encrypted SSH.

No remote secrets left behind.

No credentials stored on server.

Swarm keys remain local unless directive deploy is performed.

### Why This Matters

Railgun Install transforms MatrixSwarm deployments into true infrastructure:

Install MatrixOS on a brand-new VPS in 30 seconds

Reinstall a machine without ever opening an SSH window

Maintain fleets of servers using Phoenix

Eliminate all manual instructions (“run pip, install python, unzip zip, configure venv…”)

Zero human error

MatrixOS becomes plug-and-fire.
---

### ⚠️ Minimum Requirements for Phoenix Connectivity

Phoenix relies on **two critical relay agents** to establish communication
between the GUI and your MatrixSwarm deployment:

1. **Ingress Agent (`matrix_https`)**
   * Receives signed packets from Phoenix over HTTPS (mTLS)
   * Must be configured with a valid TLS certificate

2. **Egress Agent (`matrix_websocket`)**
   * Sends real-time updates and alerts back to Phoenix via WebSocket
   * Must use the same certificate authority as `matrix_https`

> 🛑 If your directive does **not** include both agents, Phoenix cannot launch a session.
> The cockpit will refuse to connect until at least one ingress and one egress are detected.

Minimum example snippet:

```json
{
  "agents": [
    { "name": "matrix_https", "universal_id": "matrix_https_1", "config": { ... } },
    { "name": "matrix_websocket", "universal_id": "matrix_websocket_1", "config": { ... } }
  ]
}
```

Phoenix uses these channels as its communication backbone:
```nginx
Phoenix → matrix_https → Matrix → matrix_websocket → Phoenix
```



---


## Deploying a Swarm with Phoenix Cockpit

Follow these steps to go from template → directive → encrypted swarm boot.

### 1. Edit Your Directive Template

* Templates live under:

  ```
  root/boot_directives/{template_name}.py
  ```
* Add or remove agents to fit your deployment (sentinels, watchdogs, NPC simulator, relays, etc.).
* Configure tags such as:

  * `packet_signing`
  * `connection` (https, wss, discord, telegram, openai, etc.)
  * `connection_cert`
* Example template structure: see `phoenix-02.py`.

### 2. Unlock or Create a Vault

* Start Phoenix Cockpit.
* Open or create a vault → this is where encrypted directives and swarm keys will be stored.
* No unlocked vault = no deployment.

### 3. Define Your Connections

* Open **Connections** in Phoenix.
* Add endpoints for HTTPS, WebSocket, Discord, Telegram, OpenAI, Slack, etc.
* Each connection will get a label and serial so it can be matched later.

### 4. Build a Directive

* Go to **Directives**.
* **Load** the template you edited in step 1.
* **Save** it under a clear label (this will show up in your saved directives list).

### 5. Deploy a Directive

* Select the saved directive.
* **Deploy** → give the deployment a name (must match the `universe` field inside your template).
* Assign connections:

  * Phoenix will prompt you to match each connection tag in the directive (`https`, `wss`, `discord`, etc.) to a saved connection in your vault.
* Optionally preview the directive before encryption.

### 6. Encryption & Swarm Key

* Phoenix encrypts the directive and stores it as:

  ```
  boot_directives/<universe_name>.enc.json
  ```
* It also saves the swarm key:

  ```
  boot_directives/<universe_name>/keys/<universe_name>.key
  ```

⚠️ **Important**: Secure the swarm key.

```bash
  chmod 600 boot_directives/<universe_name>/keys/<universe_name>.key
```

### 7. Boot the Swarm

From the command line:

```bash
  matrixd boot --universe <universe_name>
```

Matrix auto-resolves the directive + key, decrypts them in memory, and spawns the agents slice by slice.

✅ **Example Output**

```
Directive: /matrix/boot_directives/zzzz.enc.json
Swarm Key: /matrix/boot_directives/keys/zzzz.key
```

Once this is in place, your cockpit, logs, and panels will reflect the active swarm.

---

### Security Principles

* Vault key exists only in memory during session.
* No fallback configs, no plaintext state.
* TLS with SPKI pinning for HTTPS/WSS connections.
* Every packet cryptographically signed.
* Punji traps enforce singleton agents.

### Architecture

* Phoenix GUI (PyQt5)

  * Unlocks vault
  * Displays deployments + agent tree
  * Sends cmd_service_request via HTTPS
* MatrixSwarm Core

  * Routes packets to agents by service role
* Agents

  * Do their jobs (watchdog, oracle, npc-simulator, forensic)
  * Respond back with dict packets
* WebSocket Relay

  * Broadcasts responses to Phoenix

### Install Phoenix as a Desktop App

```bash
  pip install -e .
  phoenix
```

### License

Released under the MatrixSwarm Community License v1.1 (Modified MIT).
Free for personal, research, and non-commercial use.
For commercial use, contact: [swarm@matrixswarm.com](mailto:swarm@matrixswarm.com)

### Authorship

MatrixSwarm / Phoenix Cockpit © 2025 Daniel F. MacDonald & Contributors.

### Resources

GitHub: github.com/matrixswarm/matrixswarm

GitHub: github.com/matrixswarm/matrixos

Telegram: https://t.me/matrixswarm

Docs: matrixswarm.com

Discord: Join the Hive

Python: pip install matrixswarm

Codex: /agents/gatekeeper

Twitter/X: @matrixswarm

### Join the Hive

Join the Swarm → [https://discord.gg/CyngHqDmku](https://discord.gg/CyngHqDmku)
Report bugs, fork the swarm, or log your own Codex banner.

---

## 💙 Support Development

If you find **Phoenix Cockpit** or **MatrixOS** useful and want to support continued development,  
you can buy me a coffee here:

☕ **[ko-fi.com/matrixswarm](https://ko-fi.com/matrixswarm)**

Your support helps fund new releases, documentation, and open-source maintenance  
across the entire **MatrixSwarm ecosystem**.

---

### Status

Pre-release.

GUI live

Vault integrated

Recruiting contributors who think in systems.
