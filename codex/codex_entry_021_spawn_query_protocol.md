# 📜 Codex Entry #021 — Spawn Query Protocol

_"I don’t know its name. I just know I need it."_  
— An agent, requesting life

As MatrixSwarm matured, agents no longer waited to be spawned by directive.

They asked.  
They declared their need.  
They dropped `.spawn_request` payloads into Matrix’s inbox.

---

## 🧠 The Spawn Query Protocol (SQP)

An agent drops a file:
```json
{
  "type": "spawn_request",
  "requested_by": "oracle-agent",
  "permanent_id": "reaper-2",
  "agent_name": "reaper",
  "source_required": true,
  "purpose": "handle delegated die cookies"
}
```

Matrix, on receiving:
- Looks up spawn record
- Resolves source from descriptor, Git, fallback
- Writes `agent_tree.json`
- Spawns agent using `CoreSpawner.spawn_agent()`
- Logs to Codex

---

## ✅ Why It Matters

- Matrix becomes the root authority — responsive, not reactive
- Agents request capability dynamically
- Oracle, Commander, Sentinel… all gain the ability to extend the system
- Swarm gains **autonomy over expansion**

---

> Agents no longer wait to be written.  
> They *ask to exist.*

And Matrix, always watching… delivers.

🧠📦⚙️🔥
