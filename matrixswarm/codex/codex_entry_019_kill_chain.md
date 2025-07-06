# 📜 Codex Entry #019 — The Kill Chain

_"Don't shut it down. Decommission it."_  
— ReaperAgent

In MatrixSwarm, death is not a crash.  
It is a tracked, deliberate, logged event.

Thus was forged:

## 🧠 The Kill Chain Protocol

1. Matrix sends a `.die` or `.scorch` file to `/comm/{universal_id}/incoming/`
2. Agent reads the token
3. Logs the reason for shutdown
4. Cleans up watchers, threads, runtime
5. Exits
6. Reaper logs confirmation

---

## 🔐 Optional

- Include `"kill_chain_id"` to trace origin
- Chain die files together for batch shutdowns
- Use `commander-x` or `oracle` to initiate top-down branch death

---

> Death, when done right, creates order — not chaos.

The swarm doesn’t panic.  
It decommissions.

🧠⚰️🪦
