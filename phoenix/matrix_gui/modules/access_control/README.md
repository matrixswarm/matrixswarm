# Phoenix AI Mode access control

`VaultCoreSingleton` composes one `access_control` object per vault unlock.
The singleton facade resolves that same object; there is no second database or
independent authority. All persistence uses the vault's existing encrypted,
acknowledged save path and shared lock.

```python
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.modules.access_control.access_control_singleton import AccessControlSingleton

vault = VaultCoreSingleton.get()
access = vault.access_control
# AccessControlSingleton.get() resolves this same object.
```

## One section, one permission policy

The vault section is named `access_control`. Its policy uses the familiar
Terminal layout:

```json
{
  "schema_version": 1,
  "enabled": false,
  "approval_lifetime_seconds": 900,
  "permissions": {
    "logs.read": {
      "enabled": true,
      "deployment_ids": ["deployment-id"]
    },
    "railgun.launch": {
      "enabled": false,
      "deployment_ids": []
    }
  },
  "issuer": "generated key record, managed by the authority",
  "credentials": {}
}
```

This is a layout illustration, not an importable key record. `set_policy()`
and `create_credential()` generate real issuer records. No section is written
just by unlocking an existing vault. An absent section means disabled access.

There is one saved action/deployment permission table. Credentials identify a
client; they have no separate permission table. Each operator approval selects
an exact subset of the shared policy for one authenticated connection.
Policy and credential writes run on the vault owner thread, alongside existing
workspace-save admission. Transport threads can check or commit operations and
revoke live connections, but must queue durable administration to that owner.

- `enabled` permits requests; saving it does not approve a client.
- Lifetime is 60–3600 seconds (default 900); an approval cannot exceed it.
- A deployment action requires an explicitly allowed deployment ID.
- A global action must be registered without target fields and have an enabled
  rule with an empty deployment list. Empty lists never allow all deployments.
- Unsupported actions and incomplete targets are denied in AI Mode.
- The issuer uses the existing `cryptography` Ed25519 implementation and its own
  key, independent of Matrix signing, SSH, and vault-unlock credentials.
- Credential secrets are random; only their SHA-256 verifiers are saved. The
  issuer's private key is inside the encrypted vault. Public metadata methods
  omit keys, verifiers, and tokens.

The internal `pac1` token is a signed capability backed by a live server record.
The authority looks up a token it issued, compares it exactly, verifies its
signature, and rechecks connection, policy, target, and expiry. It does not
interpret arbitrary client-supplied token claims or algorithms. This is a local
format, not a general JWT/OAuth endpoint.

## Mode and lifetime

The trusted unlock path may pass `ai_mode=True` to
`VaultService.initialize_runtime()` or `VaultCoreSingleton.initialize()`.
The mode is fixed for that unlock. The Unlock Vault dialog offers **AI Mode
(deny by default)** first under Optional capabilities, unchecked by default.
Normal mode preserves the ordinary manual controls. The
AI Mode settings button manages the shared policy, clients, live connections
and kill switch. Enabling a stored policy never changes the unlock mode.

In Normal mode, a manual call without AI credentials retains existing behavior.
An AI connection is denied. In AI Mode, even a call without a token is denied.
Never derive the mode from a model's request or from a saved `enabled` flag.

Connections, grants, request IDs, and the unlock epoch are held only in memory.
Lock, close, reopen, or replacement revokes the composed object. Old object
references stay closed. `kill_switch()` drops every connection and latches AI
access off until another unlock; `revoke_connection()` affects one connection.
Expiry checks both monotonic elapsed time and wall time.

`revoke_credential()` disables its live connections before saving the revoked
record. If persistence fails, `VaultWriteError` explains that revocation is
effective for this unlock but was not saved. Retry before reopening. A failed
credential creation never returns a secret as successfully created.

## Trusted operator and adapter APIs

```python
from matrix_gui.modules.access_control.models import Permission, Target

access.register_action(
    "logs.read",
    target_fields=("deployment_id", "session_id", "runtime_id", "agent_id"),
)
access.set_policy(
    enabled=True,
    approval_lifetime_seconds=900,
    permissions={
        "logs.read": {"enabled": True, "deployment_ids": [deployment_id]},
    },
)
credential = access.create_credential("Gemma")  # secret returned once

# Authenticated ingress only; a connection has no approval yet.
connection_id = access.connect(credential.credential_id, credential.secret)

# Operator approval only. Resolve all target IDs from live parent-owned state.
target = Target(
    deployment_id=deployment_id, session_id=session_id,
    runtime_id=runtime_id, agent_id=agent_id,
)
grant = access.approve(connection_id, [Permission("logs.read", target)])
```

Do not expose `set_policy`, `register_action`, credential administration,
`approve`, mode selection, or the vault itself as model-callable tools.
An authenticated adapter may expose request/status operations that wait for the
operator to call the approval API. `client_label` is display text, not identity.
The adapter must derive the connection ID from its authenticated ingress;
it must not trust an unrelated connection ID supplied in a model's arguments.

`can()` is only a UI preview. Dispatch uses `commit()`:

```python
result = access.commit(
    "logs.read",
    lambda: approved_queue.put_nowait(parent_resolved_request),
    target=target,
    connection_id=connection_id,
    token=grant.token,
    request_id=request_id,
)
```

The callback is trusted code performing a bounded, synchronous local handoff.
It must not wait for a dialog, perform network I/O, or enqueue arbitrary model
code. Authorization and that handoff share the vault/revocation lock. AI request
IDs are consumed before handoff, even if it raises; duplicates cannot dispatch
again on the same connection. A new approval does not reset consumed IDs.

The handoff is the commitment boundary: revocation stops later commitments,
but cannot undo one already accepted. Adapters must define what the queue
consumer may do, enforce cancellation at any later uncommitted boundary, and
project delayed results only while their grant remains valid. A `can()` boolean
or an ordinary queued callback is never a reusable permit.
The queued request must capture validated input and exact target IDs in an
immutable parent-owned envelope, rather than read mutable model input later.

## Integration boundary

The action catalog starts empty at unlock. Opening the live gateway registers
only the five reviewed pilot actions. Unsupported legacy controls and native
session dispatch stay denied; future panel, packet and mutation adapters must
declare their exact action/target schema and validate their payload before
`commit()`. Enabling an action name in saved JSON does not supply an adapter.

Session windows run in separate processes. They cannot create an authority or
receive the `access_control` section through initialization or legacy vault
queries. They must request a parent-owned action; giving a child a boolean and
letting it perform unrestricted work is not sufficient enforcement. The new
section is excluded from `session_snapshot()`.

The live adapter uses `access_control` exclusively. **Load prior Terminal
selections for review** previews the old `terminal_access` choices without
granting or saving anything. Unsupported choices are cleared. The independent
legacy Terminal console still reads its old policy and must be closed before
the live gateway uses the same client data directory. This application's kill
switch cannot revoke a separately running legacy console's authority or undo
already committed remote work.

No Linux account, filesystem ACL, or agent permission is changed here. This is
application authorization among trusted Phoenix components, not a sandbox for
code with unrestricted access to the same Windows account or process memory.

## Live pilot and Gemma

See [GEMMA_PILOT.md](GEMMA_PILOT.md) for the testing-copy layout and operator
procedure. The live gateway reuses the existing MCP names; Hermes does not need
a second connector or client credential permission table.

On operator approval, the vault enrolls the MCP client's secret **verifier**
and issues an in-memory signed grant. Repeated approvals reuse that identity.
Revoked verifiers cannot enroll again under a different label. A fresh secret
requires a fresh operator decision. Credential labels are unverified display
text, never authority. Administrators can create a random client identity file
from the Credentials tab without printing or copying its secret.

Supported actions are `swarms.list`, `agents.list`, `logs.read`, `sessions.list`
and `sessions.open`. `swarm.inspect` requires both inventory and logs for the
same exact deployment. Logs are restricted to the fixed target's saved agent
inventory. In live AI Mode reads use the parent-owned Phoenix WSS/HTTPS session.
The gateway constructs a fixed `hive.log_streamer` request; Matrix adds a
credential-free tree projection and Log Streamer returns a bounded diagnostic
snapshot from its own universe/boot. No SSH/MatrixD fallback is attempted. The
standalone legacy Terminal still uses its fixed SSH adapter. MCP supplies no
server, path, packet handler, connector, shell command or credential.

`sessions.open` creates a **read-only AI inspection tab** and live transport in
the parent. It is required before live diagnostic reads and never boots a
swarm. It does not create a native session subprocess or load custom panels.
Connect waits for a signed current-boot handshake; a tab's `view_observed`
state alone is not network or application health. Subsequent approved tree,
thread/spawn, work and log observations appear in that tab as plain text.
Tabs belong to one connection; expiry, revoke and kill erase and close them.

Each read uses a fresh request ID and correlation nonce, verifies the saved
Log Streamer sender, and checks deployment, session, generation and boot before
processing or disclosing evidence. Matrix-signed broadcasts may refresh the
tree; unbound/old trees cannot replace it. Tree names/relationships are projected
without config/vault fields. Tree freshness and truncation remain explicit.
The MCP compact report preserves the binding and states any omitted tree nodes.
Missing process/work/log permissions do not cause automatic privilege grants.

### Gate map

| Boundary | AI Mode rule |
| --- | --- |
| Vault unlock | Explicit mode; fresh transient epoch, grants never restored |
| MCP ingress | Exact method/parameter schema; fixed saved target revision |
| Approval | Qt owner thread, actual operator decision, encrypted verifier save |
| Read admission | Signed current grant and exact deployment; bounded handoff under revocation lock |
| Session transport | Saved WSS/HTTPS only; fixed Matrix service/Log Streamer target; bounded concurrency/output/deadline |
| Callback admission | Verified sender, request nonce, session, generation and current runtime; changed boots close the old session |
| Result return | Recheck before HTTP response commitment; discard late unauthorized results |
| Qt view update | Recheck before displaying each queued result |
| Connect | Typed parent inspection adapter; ordinary subprocess Connect denied before spawn |
| Deploy / Registry / Swarms / Railgun | Legacy UI entry points denied and buttons disabled |
| Registry/deployment/workspace persistence | Final vault writer rejects unsupported AI mutations |
| Agent tree / Inspector | Read-only projected tree, thread/spawn/work/log snapshot; missing evidence stays unverified |
| Custom panels | No native panels or dynamic commands in this pilot; a typed action adapter is required |
| Legacy session IPC | Parent rejects commands, registration, queries and writes in AI Mode |
| Lock / kill / target or policy change | Revoke first, stop gateway, close AI views and remove endpoint descriptor |

Read admission commits one bounded operation; its network I/O runs outside the
vault lock so an unresponsive server cannot block revocation. A read already
admitted may initiate or complete after revoke, but further lease checks abort
it and unauthorized results are withheld. HTTP responses admitted before kill
may finish sending; already released data cannot be recalled. Do not interpret
kill as rollback of committed work.

Saved target/policy changes invalidate approval. Credential enrollment itself
does not change the target revision. Closing settings leaves the live gateway
running; **Close AI connections** revokes it but allows reopening in the same
unlock. **Kill AI** latches it off until a fresh vault unlock.

Live alert subscriptions, Railgun launches and custom panel actions await their
own typed adapters. They are not enabled by a forged policy or by generic method
forwarding. No network operation, swarm mutation or functional test is performed
by importing/configuring the gateway.
