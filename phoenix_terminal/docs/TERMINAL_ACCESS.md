# Terminal access: operator-owned monitoring toolkit

## Agreed product contract and implementation boundary

The authoring policy, independent connection lifecycle, scoped live alerts,
fixed-server Swarms/agent inventory, bounded recent logs, swarm inspection,
cockpit session listing/Connect, and guarded Railgun launch adapters are implemented:

- In Phoenix’s separate Terminal Mode window, the operator can save an exact, per-deployment
  `alerts.read`, `swarms.list`, `agents.list`, `logs.read`, `sessions.list`,
  `sessions.open`, and `railgun.launch` policy and an approval lifetime.
  The whitelists are independent; old policies leave new operations off.
  Saving does not start a
  listener, expose inventory, or approve a client.
- The policy validator rejects unknown fields and operations, foreign or
  duplicate deployment IDs, invalid lifetimes, and malformed records. It binds
  future approvals to a digest of the exact Vault snapshot.
- Phoenix Terminal has an independent connection-request broker and approval
  dialog. It
  shows an explicitly unverified client label, Vault revision, exact resources,
  operations, and lifetime; Deny is the default and dismissal or timeout denies.
  Its internal pending queue is bounded and deduplicated.
- The request endpoint is loopback-only, separate from the legacy inventory
  endpoint, and exposes no client-side approval method. Approval is bound to an
  exact client secret, request, snapshot revision, resources, and lifetime.
  Lock, disconnect, expiry, or process exit revokes it.

An approved connection carries only supported operations intersected with the
saved per-deployment permissions. For `alerts.read`, the trusted worker opens an independent
WSS connection to each permitted deployment's saved `matrix_websocket`
`payload.reception` receiver. It requires mutual TLS, the saved CA and exact
server SPKI pin, sends the existing signed hello, and authenticates/decrypts
only `swarm_feed.alert` packets. It has no generic packet dispatch. No network
connection is started before approval; no host, port or credential override,
HTTP redirect, or ambient proxy is accepted. At most 16 feeds are supported.

The broker intersects adapter availability with the saved per-deployment
policy, requires an approved unexpired client identity on every page, validates
absolute cursor bounds, caps pages and buffers, and rebuilds alerts through a
fixed redacted schema. Delete, acknowledge, mute, generic calls, caller target
overrides, and reads from unselected deployments remain unavailable. Approved
status reveals only resources with effective operations. Pending requests
reveal neither operations nor resource IDs.

Feeds run on a separate bounded background event loop, not the Qt thread.
Approval leases are checked independently of GUI refresh/client polling. Expiry,
disconnect or lock denies reads immediately; worker cancellation closes the
feed. A changed grant clears buffered alerts and rotates the stream ID. Paging
after cursor zero requires that stream ID; stale cursors cannot silently cross
approvals. The buffer retains 500 alerts per feed; pages are capped at 200.

This is a **live-only** feed: it cannot replay alerts from before connection.
Every page reports connection state, a fixed diagnostic code, stream identity,
possible delivery loss and rejected-packet count; buffer retention loss is
reported separately. A connected source has verified TLS/pin and submitted its
hello, not proven swarm health. The server has no hello acknowledgement. An
unreachable source or empty alert list must never be presented as a healthy
server. Credentials stay within the trusted operator runtime; temporary TLS
identity files are removed after SSL context loading. No credentials are
returned through the client API.

Functional health probes, panel actions and restarts are still future adapters.
Bounded log sampling and process/heartbeat observations are implemented; they
do not exercise every function or certify a release. The diagnostic commands
require the updated MatrixOS script/module on the fixed saved server.
The legacy read-only inventory console is a separate compatibility
endpoint. The sections below remain the controlling contract for those future
adapters, not a claim that they are already available.

Phoenix GUI is the operator's vault authoring application. Phoenix Terminal is
the separate operator-controlled runtime used by an agent. The Terminal Mode
window contains authoring controls; opening it never grants access or starts a listener.

The prepared vault is the complete resource boundary. If it contains two
deployments, those two deployments are the entire available toolkit. There is
no implicit action authority over deployments in another vault or elsewhere on a server.
An explicitly whitelisted Swarms inventory may observe other active universe
names/resource totals on its fixed server, but that grants no authority to them.
The operator constrains operations within that boundary using **Terminal
access** settings. Inclusion of a credential permits its internal use only for
an allowed operation; it does not permit the agent to retrieve the secret.

The compatibility inventory console described in OPERATOR_TOOLBOX.md still
requires select/enable and does not implement saved operation policies, live
sessions, logs, alerts, or panel adapters. The new approval endpoint implements
the connection lifecycle and the explicitly permitted adapters above.
Neither endpoint grants general server administration.

## Immutable resources, explicitly allowed operations

The agent cannot edit the toolkit it is given. These capabilities are excluded
from the agent API, including from generic panel or packet escape hatches:

- Editing, creating, or deleting saved deployment definitions.
- Adding, deleting, replacing, injecting, or reparenting agents.
- Changing source, saved configuration, constraints, or credentials.
- Changing a target host, port, SSH account, pinned host key, or deployment's
  credential reference; caller-supplied target overrides are rejected.
- Editing terminal policy, self-approving a connection, or exporting the vault,
  passwords, private keys, or raw sealed deployment material.

Within those fixed resources, the operator can whitelist named operations:

- Open a connection session to an existing deployment; list or inspect sessions.
- Read health, agent inventory, logs, or swarm alerts.
- Use explicitly supported panel actions, each with validated parameters.
- If separately supported and whitelisted, launch the exact prepared swarm on
  its fixed target. Opening a connection session is NOT deploying a universe.

Unlisted operations are denied. Permission to read or open a panel does not
permit every button in it. For example, matrix_ssh status refresh and perimeter
lockdown are different capabilities; the latter can interrupt communications.
Runtime actions with side effects need separate policy and possibly fresh
approval. They must not become an indirect way to edit the immutable resources.

Public tool discovery describes only the effective allowed operations and
their schemas. Raw credentials remain inside the trusted runtime. Per-deployment
and per-agent restrictions can narrow vault-wide settings, never widen them.

## Operator approval and lifetime

1. The operator privately opens the prepared vault in Phoenix Terminal.
2. A client requests a connection. No vault inventory or operational access is
   released merely because a request arrived.
3. The operator receives **Allow connection?**, showing the requesting client,
   vault/toolkit, effective resources, allowed operations, and access duration.
   An unverified client-supplied label must not be presented as verified identity.
4. Deny is the default. Dismissal, timeout, or failed approval grants nothing.
   Requests must be bounded and deduplicated, not produce an unbounded prompt
   queue. The client API contains no approval method.
5. Approval binds to that exact authenticated client/request, a fixed vault
   revision, policy, and lifetime. It grants no additional operations beyond
   the whitelist. Another client cannot reuse that decision.
6. Lock, explicit revocation, runtime exit, or expiry revokes access and pending
   approvals. Reconnecting does not extend an expired grant.

The operator confirmed that **Allow connection? belongs to Phoenix Terminal**,
not Phoenix GUI. It is an independent Terminal-owned approval dialog; Phoenix
GUI uses only an opt-in Connect/session endpoint, never the retired generic
action bridge. It independently checks the Terminal grant, current unlocked
Vault policy and exact Vault revision on its Qt thread. A session open reuses an
existing tab, never starts or restarts a server swarm. Closing/expiry revokes tool
access; already-opened tabs remain operator-owned.
On a machine without a display, this desktop approval path must fail with a
clear diagnostic rather than silently auto-approve. A future terminal-text
approval presenter can implement the same contract without changing authority.

The new approval path uses all deployments in the prepared vault as the resource
ceiling; it does not require an additional assignment-selection step. The
existing inventory console's select/enable workflow remains separate legacy
behavior while operational adapters are implemented and tested.

Changes in another Phoenix process do not live-update an existing terminal
snapshot. Reopening/reloading must revoke the old grant and require approval
for the changed toolkit; newly added records must never widen an active grant.
Policy and fixed-target checks apply at every dispatch, not just tool discovery.

The current loopback bearer token is a possession credential, not verified
per-agent identity. Unrestricted execution as the operator's OS account can
bypass application-only restrictions. Independent OS identity and protected
credential/runtime storage are prerequisites for claiming that stronger boundary.

## Room-by-room implementation order

1. Dashboard: Terminal access policy summary and scoped swarm-alert reads.
2. Connection approval and session management: identity, immutable snapshot,
   expiry, revocation, and exact deployment binding.
3. Agent tree, health, and logs: scoped responses, redaction, pagination, and
   explicit retention gaps.
4. Custom panels: inventory and approve individual action adapters; never expose
   generic packet sending, arbitrary handlers, shell commands, or GUI clicking.
5. Railgun, if included: whitelist a prepared deployment revision and fixed
   destination; preserve durable request identity and uncertain-result handling.

No UI permission should claim an unsupported operation is enabled. A saved
authoring choice for an unimplemented adapter must be visibly marked unsupported
and rejected by the runtime.

## Required regression cases

- No approval: no inventory, logs, alerts, sessions, or remote dispatch.
- Approved client: only the vault's existing resources and whitelisted actions.
- Alternate host/account/pin/credential, foreign IDs, unknown operation, forged
  parameters, or generic panel command: reject before network dispatch.
- Same universe name on two hosts: never treat as the same deployment.
- Agent or deployment edit requests: reject, regardless of connection approval.
- Read permission cannot acknowledge, delete, mute, restart, or change settings.
- Close, expiry, denial, and late approval races cannot revive access.
- Changed toolkit or policy requires a new approved snapshot; no silent widening.
- Local CLI and optional MCP use the same authorizer; neither bypasses it.
- Synthetic vaults only in tests; no production credentials or live dispatch.

Current behavior and these future guarantees must be reported separately.

## Swarms and Railgun: fixed targets, never replacement

Both operations take only an exact permitted saved deployment ID. The runtime
privately resolves its saved `ssh_serial` to the Registry profile and requires
the recorded host, port and host-key pin to match. Credentials stay private;
the approval dialog shows the fixed SSH account/server, universe and pin.
Caller-supplied connections, hosts, commands, options and universe names are
rejected. Ambient SSH-agent authentication is not accepted by these adapters.

`terminal swarms DEPLOYMENT_ID` runs one `matrixd list --json` on that saved
server using pinned SSH. It returns a bounded projection of active universe
names and resource totals. No kill/kill-all, automatic refresh or authority over
observed universes is exposed. Network work does not hold the approval lock;
lease expiry/lock/disconnect stops the read and suppresses its response.

`terminal railgun launch DEPLOYMENT_ID --operation-id ID` queues a bounded
asynchronous job. ID must be 32 lowercase hex characters generated ONCE for an
intentional launch. Keep it and reuse it for all retries. Query the same ID with
`terminal railgun status DEPLOYMENT_ID --operation-id ID`. The server request ID
is deterministically bound to the exact Vault revision, deployment and operation
ID, including after a Terminal restart. The server's durable receipt enforces
at-most-once execution and retains an interrupted universe lock for operator
reconciliation. A completed receipt is not proof of live swarm health.

This adapter launches the exact sealed bundle and saved service account with
saved verbose/debug/rug-pull/protect-memory flags and runtime capabilities.
It NEVER inherits reboot, reboot-new, reboot-id, or clean privileges from a GUI
deployment. It cannot replace or stop an active swarm. The shared server request
wrapper checks for any surviving agent in that universe INSIDE its durable
universe lock before provisioning/booting. Refusal is recorded with exit 73;
retrying the refused operation remains refused even if the swarm later stops.
A fresh intentional launch needs its own operation ID and existing approval.

Update MatrixOS's `scripts/matrix-railgun-request` as well as Phoenix/Terminal
before testing Railgun. Its `--inactive-protocol` probe must return
`railgun-inactive-v1`; an older server fails closed instead of losing the guard.
Use the normal operator-managed server update workflow, not an agent bypass.
All concurrent Railgun clients must use the durable wrapper. Direct server/root
administration remains outside the application permission boundary.

Job states are `queued`, `running`, `completed`, `refused_active`, `failed`,
`cancelled`, or `outcome_unknown`. Dispatch followed by lost acknowledgement,
expiry or revocation is **unknown**, not failure or success. Do not generate a
fresh operation ID to bypass it. Once an operation is dispatched, revocation
cannot undo its remote side effects; it stops further client access/work and
requires operator receipt/live-state reconciliation. Raw server output is not
exposed. Jobs are scoped to the approved client and capped at 32 per runtime;
SSH concurrency is capped at four and output at 1 MiB per operation.

For MCP, run `python -m phoenix_terminal --data-dir STATE mcp --terminal-access`.
This selects explicit approval/request/status/disconnect, alert, Swarms and
Railgun tools using the SAME local client identity and authorizer as the CLI.
Plain `mcp` retains the separate legacy inventory toolset. No generic RPC or
client approval tool is exported.

## Operator smoke test for the resumed work

1. In Phoenix's Terminal Mode window, whitelist `swarms.list` and `railgun.launch`
   separately for the desired saved deployment. Keep unrelated deployments
   unchecked, then save. Existing grants do not change until Terminal reopens.
2. Close the old Terminal, update the local code and server wrapper, and reopen
   the same prepared Vault privately. Request a connection and inspect/approve
   its fixed destination and effective operations.
3. Read Swarms inventory using the permitted deployment ID. Check its existing
   universe appears; an unselected deployment ID must be denied before SSH.
4. While that universe is ALREADY ACTIVE, generate one operation ID and queue
   Railgun. Poll its status: expect `refused_active` / exit 73. Existing agents
   must remain undisturbed. Retrying the SAME ID must not boot anything.
5. Disconnect. Swarms, alerts and Railgun must all deny further access. Do not
   stop an existing swarm merely to test successful launch: use a separately
   prepared inactive test universe when an intentional launch is wanted.

PowerShell client commands (same data directory as the operator Terminal):

```powershell
& $phoenixPy -B -m phoenix_terminal --data-dir $testState terminal status
& $phoenixPy -B -m phoenix_terminal --data-dir $testState terminal swarms 'PERMITTED_DEPLOYMENT_ID'
# Generate ONCE, then retain this ID. Do NOT rerun this line for retries.
$terminalLaunchId = [guid]::NewGuid().ToString('N')
& $phoenixPy -B -m phoenix_terminal --data-dir $testState terminal railgun launch 'PERMITTED_DEPLOYMENT_ID' --operation-id $terminalLaunchId
& $phoenixPy -B -m phoenix_terminal --data-dir $testState terminal railgun status 'PERMITTED_DEPLOYMENT_ID' --operation-id $terminalLaunchId
```
