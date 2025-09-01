**codex\_entry\_046\_agent\_tree\_doctrine.md**

> "No pulse unmeasured. No agent unseen."
> —Phoenix Doctrine, Article 46

---

### NAME:

**The Agent Tree Doctrine**

### CODE:

`046`

### CLASS:

Swarm Visibility / Operational Continuity

---

### OVERVIEW:

The Agent Tree Doctrine defines the canonical method for *real-time swarm introspection* via agent beacons, spawn lineage visibility, and recursive hierarchical tree projection.

It asserts:

* That every agent must emit a measurable pulse.
* That Matrix must detect, time, and log each pulse.
* That Phoenix must display the heartbeat of the Swarm.

No process may be assumed alive unless it proves so by signal.

---

### CORE SIGNALS:

Each agent emits `poke.<thread_token>.<timeout>.<sleep>.<wake_due>` files in its `hello.moto/` directory. These empty files update their `mtime`, allowing Matrix to determine the last pulse delta.

Common thread tokens:

* `worker` → main process logic (`🧠`)
* `packet_listener` → command receiver (`🛱️`)
* `https_service`, `websocket_service` → server loop (`⚙️`)
* `websocket_clients` → client connect signal (`🔌`)
* `reaper_patrol`, `scavenger_sweep`, `tripwire_watch` → sweepers and watchers

A missing or stale beacon is declared `❄️ frozen`, `⚠️ stale`, or `💥 failed`.

---

### SPAWN INTELLIGENCE:

Each agent creates `spawn/` files named:
`<timestamp>_<uuid>.spawn`

These track creation lineage. Matrix calculates:

* `spawn.count`
* `spawn.last_seen`
* `spawn.flip_tripping` → spawn rate anomaly

---

### PHOENIX RENDERING:

The Phoenix GUI must:

* Render agent hierarchy in tree form
* Display health column as:

  * `🧠` worker
  * `🛱️` listener
  * `⚙️` service
  * `🔌` client
  * `🔖` spawn
  * Colored icon glyphs for each status (`🔴` = failed, `⚠️` = stale, etc.)
* Auto-expand `matrix` root
* Preserve expanded state on updates
* Display Hive glyph spinner while waiting for first payload
* Support click-to-inspect panel showing:

  * Full `agent_status`
  * Thread timestamps + delta
  * `spawn.count`, flip\_tripping state
  * Configuration payload

---

### ENFORCEMENT:

Matrix's `perform_agent_consciousness_scan()` shall:

* Scan all `hello.moto/` paths
* Detect missing/stale/failing threads
* Tag agents accordingly
* Push `agent_tree_master.update` to all Phoenix relays

Any agent without a recent pulse shall be considered **critically nonconscious**.

---

### CLOSING:

This doctrine ensures that MatrixSwarm operates with *total situational awareness*. When combined with the Kill Chain (019) and Spawn Query Protocol (021), no node may vanish unnoticed, and no process may lie dormant without being seen.

In the Hive, every breath is counted.

---

**AUTHORITY:** Phoenix Core / MatrixSwarm
**VERSION:** v1.1
