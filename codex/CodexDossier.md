# CodexDossier.md
MatrixSwarm Intelligence Ledger

Created by Daniel F. MacDonald + ChatGPT-4  
This file captures the architecture, doctrine, revelations, and system design milestones of the swarm.

---

## 🧠 Swarm Architecture Core Beliefs

- Swarm is file-native. Folders are structure. Files are speech.
- All operations are socketless, stateless, and resurrectable.
- Matrix is not an orchestrator — she is a sovereign.
- Tree = truth. Agents follow it or fall.

---

## 📡 Swarm Resolution Protocol (SRP)

- Agents send `.que.cmd` files to represent intent with `queue_id`
- The resolver agent (`ServiceDirectoryAgent`) verifies targets (by service or universal_id)
- On success, agents receive a `resolve_response` with matching `queue_id`
- Queue file is reopened and injected — original packet is updated and routed
- No blind delivery. No dead-letter spam. No ghost paths.

---

## 🔁 Command Handling Protocol

- All agents support `cmd_{command}` handlers via `BootAgent`
- `.cmd` files are automatically routed to these handlers
- Matrix can dynamically route `.cmd`, `.json`, `.alarm`, etc. via `route_payload`

---

## 🧬 Important Agent Protocols

- `SwarmQueueMixin` enables safe queue dispatching and receipt
- `AlarmStreamerAgent` broadcasts `.alarm` packets over secure WebSocket
- `CodexVerifierAgent` confirms authorship `.ots` signatures on boot
- `ServiceDirectoryAgent` watches tree + injects new services on file events

---

## 🔐 Security and Authorship

- All Codex artifacts are timestamped using OpenTimestamps + DigiStamp
- No commits happen before stamping
- `AUTHORS_DECLARATION.txt` is signed and pushed in each archive
- Codex logs every milestone and agent lineage


---

## 🧱 Swarm Default Comm Spec v1.0

Standardized by Daniel F. MacDonald

As of 2025-05-06, all agent spawn operations via CoreSpawner now initialize the following comm pod structure by default:

/comm/{agent}/
├── hello.moto/     ← Heartbeat ping directory
├── payload/        ← Incoming job packets (.json)
├── incoming/       ← Matrix-injected commands (.cmd)
├── queue/          ← Async queue entries (.que.cmd)
├── stack/          ← Multi-stage mission persistence
├── replies/        ← Resolution and ACK drops
└── broadcast/      ← Swarm-wide shared visibility channel

These are now generated in CoreSpawner using `default_comm_file_spec`.

No directive files or boot scripts need to define comm folders manually.

This update guarantees structural consistency, reduces config bloat, and prepares the swarm for modular expansion across agent classes and mission protocols.

---
## 🧠 Logged and sealed, General.

📜 CodexDossier.md now includes:

📡 Swarm Broadcast Protocol v1.0

Payloads delivered to /broadcast/ on all agents

Matrix excluded by default to avoid echo

BroadcastListenerMixin defines agent behavior

GUI2 and Matrix both now support real-time swarm messaging

You're running a system that can now speak to every node with one packet.

Ready to wire the GUI2 dropdown + auto-broadcast builder? One click and the whole swarm listens. 

---
###Let’s finish the protocol and log it as:

✅ Agent Replacement Protocol v1.0
replace_agent triggers .die

Matrix delays spawn until heartbeat delta or scavenger-confirmed

Reaper executes, Scavenger confirms, Matrix respawns

Codex logs origin, replacement, and timestamp

GUI2 shows replacement lineage (optional)

---
## MEMORY SHARD
🔐 Memory Shard: Final Broadcast & Spawn Protocols (May 6)
✅ Broadcast Protocol v1.0
target_universal_id: "broadcast" now routes payloads swarm-wide

Drops files into /comm/{agent}/broadcast/broadcast_{timestamp}.json

Matrix excludes herself unless include_matrix=True

Agents use BroadcastListenerMixin to watch and react with:
 
✅ TreeParser Enhancements
walk_tree(): full recursive agent walk

all_universal_ids(include_matrix=False): feeds broadcast targets

has_node(universal_id): used by Matrix to verify agents before delivery

✅ Heartbeat Protocol v1.1
Agents write to:

delta = time.time() - os.path.getmtime(ping_file)
✅ Agent Replacement Protocol
replace_agent now fires correctly (missing elif was fixed)

Reaper sends .die, Scavenger clears, Matrix respawns

Codex updated with new install

Reaper exits with honor: self.leave_tombstone_and_die()

✅ Boot Safety Protocol v1.0
ensure_comm_dirs(path) added to BootAgent and Oracle

Ensures agents don’t crash on missing folders like /logs/, /payload/, /queue/

Called from worker_pre() on boot

✅ GUI2
Dropdown target added for "broadcast" folder

Payload editor supports full route_payload

Broadcasts confirmed to reach 12 agents (Matrix excluded by default)

🔐 Swarm-Safe Rule: Memory Shard Write Protection
📜 Purpose:
Ensure agents never create phantom or unauthorized comm paths when writing response messages, status updates, or memory shards.

✅ Rule Summary
An agent may only write to a communication path if that exact path already exists.

🛡 Enforcement Pattern
Use this check before writing to any external file path like reply_to, ack_path, resolve_response, memory_shard_path, etc:

if not os.path.exists(os.path.dirname(target_path)):
    self.log(f"[{self.command_line_args['universal_id']}] SKIPPED write to nonexistent path: {target_path}")
    return
This ensures:

No phantom /comm/... folders

No accidental resurrection of dead agents

No broken lineage in Codex

No ghost directories left behind

def cmd_resolve(self, command, packet):
    payload = packet.get("payload", {})
    reply_path = payload.get("reply_to")
    role = payload.get("role", "").lower()

    if not role or not reply_path:
        self.log("[RESOLVER][SKIP] Missing role or reply_path.")
        return

    if not os.path.exists(os.path.dirname(reply_path)):
        self.log(f"[RESOLVER][SKIP] Phantom prevention: {reply_path} does not exist.")
        return

    matches = self.directory.get(role, [])
    response = {
        "role": role,
        "targets": matches,
        "count": len(matches)
    }

    with open(reply_path, "w") as f:
        json.dump(response, f, indent=2)

    self.log(f"[RESOLVER][REPLY] → {reply_path} ({len(matches)} matches)")
📁 Dossier Log Entry
MemoryShardWriteRule_v1.0

Activated: 2025-05-06

Applies to: All agents writing to cross-agent reply_to, ack, broadcast, resolve, queue, stack

Enforced by: os.path.exists(os.path.dirname(path))

Exemptions: None. Phantom agents are forbidden.


---
## ⚔️ Final Directive

This swarm will outlive its creators. But it will never forget who forged it.