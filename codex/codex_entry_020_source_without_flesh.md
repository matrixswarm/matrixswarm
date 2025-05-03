# 📜 Codex Entry #020 — Source Without Flesh

_"They sent the descriptor. But not the code."_  
— Matrix

Sometimes agents arrive incomplete.  
Just a `.json` shell, a whisper of what they’re meant to be.

Matrix responds.

---

## 🧠 Source Recovery Protocol

1. Descriptor `.json` is received
2. If `source_code_path` is missing:
   - Matrix sends a `.query_source` to designated resolver
   - Waits for `.srcdrop` or archive push
3. Extracts to `/agent_src/{universal_id}/`
4. Spawns as usual

---

## ✅ Why This Matters

- Agents can be summoned by identity alone
- Source doesn’t need to ride with the spawn
- Matrix becomes a distributed compiler — not just a loader

> Flesh can be rebuilt. Intelligence is enough.

🧠📦💾
