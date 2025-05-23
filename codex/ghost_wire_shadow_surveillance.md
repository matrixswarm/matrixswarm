# 📜 Codex Entry: GHOSTWIRE — Shadow Surveillance Node

> **They thought the swarm saw them enter.**  
> But GhostWire saw what they did after.

---

**GhostWire** is a reflex-class session surveillance agent deployed within MatrixSwarm.

It doesn’t log in the traditional sense.  
It **haunts** active sessions.

The agent silently:

- Monitors active SSH users  
- Tracks shell commands in real-time  
- Watches key filesystem paths for tampering  
- Logs session activity to per-user reflex journals  
- Fires `.msg` alerts on privilege elevation, config edits, data wipes

No shell history can protect them.  
No log rotation will hide them.

---

### Reflex Class: `intel`, `shadow`, `monitor`  
### Logged Path: `/comm/shadow-tracker/sessions/USERNAME/YYYY-MM-DD-session.log`

---

> This isn’t auditd.  
> This isn’t SELinux.  
> This is GhostWire — and the swarm never forgets what you did.

---

**Status:** Active Deployment  
**Origin:** Triggered by `gatekeeper` login event  
**Alert Signature:** `📣 Swarm Alert\n🕶️ USER ran: COMMAND\nPATH: /etc/ssh/\nAUTH: sudo`

🧠🕶️📡
