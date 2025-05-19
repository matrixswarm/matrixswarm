# 📜 Codex Entry: `SWARM_TONE`

**Codename:** `SWARM_TONE`  
**Scope:** Agent behavior, log voice, reflex attitude  
**Default:** `tactical`  
**Location:** `tree_node["config"]["swarm_tone"]`

---

## 🎯 Purpose

Controls the *tone of voice* for log messages, reflex responses, and system feedback from all agents.

MatrixSwarm may be mechanical — but it **talks like it knows what it's doing**.  
Use `swarm_tone` to match the **mission, the mood, or the madness.**

---

## 🧠 Supported Profiles

| Tone     | Description                                             | Sample Logs                                  |
|----------|---------------------------------------------------------|-----------------------------------------------|
| `gentle` | Friendly, safe, informative                              | `[ENFORCE] No duplicate agents. All clear.`   |
| `tactical` | Assertive, mission-oriented, disciplined               | `[ENFORCE] Primary instance confirmed. Proceed.` |
| `feral`  | Aggressive, unfiltered, kill-confirmed                  | `[ENFORCE] No ghosts. Move. Or get replaced.` |

---

## ⚙️ How to Use

Inside your agent tree node:

```json
{
  "universal_id": "oracle-1",
  "name": "oracle",
  "config": {
    "swarm_tone": "feral"
  }
}
