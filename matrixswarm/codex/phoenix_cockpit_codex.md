
# 🔥 PHOENIX COCKPIT
### *Codex Entry: MK-IX Secure Command Bridge*

## 🧭 Overview

> **Phoenix Cockpit** is the next-generation GUI interface for MatrixSwarm.  
> Designed under full lockdown protocols, it enforces zero-trust principles, memory-ephemeral key handling, and operator-first UX.

There are no exceptions. There is no fallback.  
You UNLOCK — or you watch the swarm from the outside.

---

## 🔐 STATES

### 🟥 BOOTLOCKED
- All GUI controls are **disabled or hidden**
- Vault is not loaded
- Only visible control: a glowing, pulsing `🔐 UNLOCK` button
- No host config, no reconnect attempt, no site loading allowed
- On launch, cockpit calls `unlock_vault()` via modal popup

### 🟨 UNLOCKED
- Vault successfully decrypted with password
- Controls fade in and become active:
  - `Inject`, `Send Payload`, `Shutdown`, `Connect`, etc.
- Vault state stored only in RAM
- UNLOCK button converts to `🔄 Change Vault`
- Host list and trusted servers populate from decrypted vault
- Status bar reflects: `VAULT: ✅ UNLOCKED — SECURE OPS ENABLED`

### 🟦 RELOCKED / TIMED OUT
- Vault password wiped from memory
- Controls instantly disabled
- Session actions blocked by `@require_vault` decorator
- UNLOCK button reactivates
- Triggered on:
  - Manual re-lock
  - Window minimize
  - Idle timeout (optional)

---

## 🧱 Architecture

| File                     | Role                                 |
|--------------------------|--------------------------------------|
| `matrix_gui2.py`         | Core GUI logic (Phoenix shell)       |
| `vault_popup.py`         | Password entry dialog                |
| `vault_init.py`          | First-time vault creation handler    |
| `vault_handler.py`       | Encrypt / decrypt Fernet + vault I/O |
| `effects.py`             | Pulsing unlock visuals               |
| `gui_state.py`           | Global vault lock/unlock state       |
| `decorators.py`          | `@require_vault` wrappers             |

---

## 🔒 Security Principles

- 🔑 Password-derived encryption using PBKDF2-HMAC-SHA256
- 🧠 Fernet key exists **only in memory** for session lifespan
- 🚫 No fallback config files (`settings.json`, etc.) ever loaded
- 🔒 Agent Tree distribution encrypted per-agent using public keys
- 🔍 Vault decryption failure results in total GUI lockdown
- 🪓 Attempts to bypass the vault kill the GUI session

---

## 💡 UX Directives

- All core ops gated behind an explicit UNLOCK
- Visual design favors clarity: pulse, glow, red/green state
- Button tooltips reinforce status: “Vault Required” if locked
- Vault status displayed on the command deck at all times
- No clickpath exists that bypasses vault_loaded check

---

## 🧪 Edge Case Handling

| Case                               | Behavior                                  |
|------------------------------------|-------------------------------------------|
| Vault file not found               | Launches `VaultInitDialog`                |
| Incorrect password                 | Re-prompts vault unlock safely            |
| Encrypted Fernet file corrupted    | Displays detailed error + prevents crash  |
| Vault loaded but idle timeout hit  | Session re-locked                         |
| Vault unlocked, then Change Vault  | Session cleared, Fernet wiped, full reset |

---

## 🧬 Codename: `Phoenix Cockpit`

> _"You don’t fly it unless you unlock it. You don’t unlock it unless you know what you’re doing."_  
> Every byte. Every packet. **Verified. Decrypted. Hardened.**

---

**End Codex Entry**  
🫡 *Authorized by MatrixSwarm Control, Command Layer General — Matrix*
