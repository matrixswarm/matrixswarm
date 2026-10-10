# Gemma pilot: live Phoenix AI Mode

This is a read-only diagnostic pilot. Native agent panels and swarm mutations
remain blocked. Validate the workflow manually before treating it as stable.

## Testing copy

Keep these source directories paired:

| Monorepo source | Testing destination |
| --- | --- |
| `phoenix` | `C:\Users\pete\PycharmProjects\phoenix_gui` |
| `phoenix_terminal` | `C:\Users\pete\PycharmProjects\phoenix_terminal` |

Copy application code only. **Preserve `phoenix_gui\vaults`, `.venv`, `.idea`
and all existing testing vaults.** Do not mirror/delete the destination.
The paired Terminal source contains the updated broker and MCP descriptions;
copying only `phoenix` is insufficient. Hermes can continue using its existing
MCP runtime against the updated monorepo Terminal source. Restart/reload MCP
after copying, and restart Phoenix so it loads one consistent checkout.

## Server prerequisite

Deploy the matching MatrixOS code through the normal operator workflow before
this pilot. The running swarm needs the updated `matrix` routing/tree projection,
Log Streamer **1.3.1**, and the shared `live_diagnostics.py`,
`swarm_processes.py` and updated `swarm_diagnostics.py` core modules. Copying
Phoenix locally does not update a running swarm. The saved deployment must
contain WSS ingress, HTTPS egress, one Matrix, one Log Streamer, and their
callback/TLS certificates. No Linux privileges or file permissions are granted
by this change; unreadable thread/work/log files remain coverage limits.

Verify that the running Matrix and Log Streamer processes started after the
server code update. Updated files on disk do not reload handlers in an existing
agent process. Use the normal operator workflow to restart/redeploy the selected
swarm when needed, and confirm a new runtime boot before requesting AI access.
The live-alert and Railgun columns show Pending/Blocked in this pilot; neither
can be selected or saved as AI permission. Recent-log findings use Logs / inspect.

Matrix must normalize the runtime `comm_path` before extracting its boot ID:
the spawner supplies a trailing `/comm/`. Both the diagnostic tree snapshot and
tree broadcasts must use that boot, never the directory name `comm`. Server
read failures return fixed codes such as `TREE_RUNTIME_MISMATCH`; Phoenix
includes the failed operation and code without exposing exception text or paths.

The diagnostic file reader uses Linux `O_PATH` for ancestor traversal and opens
only the final directory for reading. This supports execute-only ancestors such
as `/matrix/universes` without granting directory listing there. Every component
still rejects symlinks. Install this core update before interpreting a report
in which the tree is present but all telemetry reads are unreadable; do not
broaden server permissions to work around the earlier reader behavior.

The live gateway uses Phoenix's WSS/HTTPS session, with signed and encrypted
callbacks. It does not call SSH or MatrixD as a fallback. The standalone legacy
Terminal retains its previous SSH adapter.

## Open Phoenix

Connect waits for two separate observations: the pinned HTTPS command endpoint
returns HTTP 200 with `status: ok`, and Log Streamer's signed callback arrives
over WSS with the correct fresh boot binding. Socket connection or HTTP success
alone does not complete Connect. Temporary failures permit three total read-only
handshake attempts within 50 seconds, with 2- and 4-second pauses. Every attempt
has new correlation IDs; late receipts/replies cannot complete another attempt.
Trust/access failures, malformed replies, boot changes, revocation and expiry
stop immediately. Phoenix shows the current wait/retry stage. On final failure
it stops that session's connectors; Gemma reports the error and stops. AI startup
is owned by this bounded Connect operation; no background reconnect monitor runs.
Normal log/inventory reads do not automatically retry.

Successful live Connect returns `transport_readiness_verified: true` and
`connection_readiness` with attempts, HTTP status, verified reply and runtime ID.
This does not assess agent health. `swarm_started: false` means Connect did not
start a swarm, not that the remote swarm is stopped. The local MCP client allows
70 seconds for Connect, leaving room for UI dispatch around the 50-second wait.

Close the old standalone Terminal access window first. Use the same data
directory already configured in Hermes (the current pilot uses
`PhoenixTerminal-ApprovalTest`). This environment variable contains a path,
not a credential:

```powershell
$env:PHOENIX_TERMINAL_DATA_DIR = 'C:\Users\pete\AppData\Local\PhoenixTerminal-ApprovalTest'
Set-Location 'C:\Users\pete\PycharmProjects\phoenix_gui'
& '.\.venv\Scripts\python.exe' -B '.\phoenix.py'
```

1. In **Unlock Vault**, check **AI Mode (deny by default)** at the top of
   **Optional capabilities for this session**, then unlock a testing vault.
2. Open **AI Mode → Policy**. Optionally load prior Terminal selections for
   review. Enable agent inventory, logs, Session list and **Connect** for the
   same deployment. Swarms inventory is optional. Connect is required before
   live reads; saving policy does not silently enable it.
3. Save the policy. Select **Connections / Kill switch**, check the Hermes
   client data directory, then choose **Open AI access**.
4. Send Gemma the prompt below. Approve the request in Phoenix; approve only
   the displayed scopes you intended. No typed “approved” reply is needed if
   the decision arrives within the tool's 45-second wait.

## Gemma prompt

> Use the phoenix-term-ops skill and Phoenix Terminal MCP tools. Request access
> as Gemma and wait for the operator decision. If approved, use the returned
> deployment IDs and exact tool_calls. List permitted sessions, then call
> phoenix_terminal_connect for the permitted deployment BEFORE diagnostic
> reads. Wait for Connect to finish its bounded readiness checks; do not repeat
> the call yourself. Verify transport_readiness_verified is true,
> connection_readiness.state is ready, and session_binding says phoenix_session
> with the current runtime_id. Report its attempt count, then inspect the swarm.
> Report findings with exact agent
> IDs, timestamps and evidence; distinguish process presence, thread health and
> work progress. Include tree coverage, boot identity, omissions and sampling
> limits. If Connect fails or is not permitted, report that limit and stop.
> Distinguish missing records from unreadable records. Read attempts do not mean
> readable log content. Compact tree omissions do not mean source nodes are missing.
> Do not boot, restart,
> edit, repair or call Railgun. If denied, revoked or expired, stop. Never invent
> resource URIs or repeatedly request approval.

## Manual acceptance checks

- Before approval, no deployment resources or diagnostics are disclosed.
- Approve: Gemma sees the exact selected deployment and finds current evidence.
- Connect: one read-only AI tab appears; repeated Connect reuses that client's
  tab. A fresh signed boot binding is returned. The swarm is not started or restarted.
- Delayed startup: Connect shows wait/retry stages and returns ready only after
  HTTP acceptance and a signed boot reply. Temporary failure stops after at most
  three attempts/50 seconds. Authentication/trust failures do not retry.
- Kill/revoke during a retry pause: the next send is denied and no late response
  is disclosed. An expired or failed Connect is not repeated by Gemma.
- Inspect: `session_binding.transport` is `phoenix_session`; tree, thread/spawn,
  work and log evidence refer to the same runtime. Missing/unreadable evidence
  is reported. Resource metrics are unavailable rather than invented zeroes.
- Missing server update or broken connectors: Connect times out with operator
  guidance. Gemma stops; it does not switch to SSH or repeatedly retry.
- Deny: Gemma stops; the request reveals no resources.
- Revoke selected connection during a read: new reads are denied, late results
  are withheld, and its view closes.
- Operator restarts the swarm between reads: the next signed reply with a
  different runtime closes the old AI session. Reconnect deliberately; no old
  boot is merged into the new snapshot. Gemma itself must not restart anything.
- Revoke its credential: a new request with that identity cannot regain access.
- Kill AI: approvals end, tabs close, the endpoint disappears; reopening access
  is blocked until the vault closes and unlocks again.
- Lock/reopen: old request identities and signed grants cannot inspect the new
  unlock. A new approval is required.
- Unsupported/global UI actions stay disabled; ordinary Connect, custom panel
  commands, edits and Railgun calls fail closed.
- Reopen in Normal Mode: ordinary manual controls are available again.

These checks are an operator procedure, not an automated test result. An
observed process or recent heartbeat still does not prove useful agent work.

## Target context and operation recovery

Install the updated `agent_progress.py` and `swarm_diagnostics.py` shared core,
plus the updated Tripwire Lite, Site Sentinel, Log Watcher (including its shared
log reader), and Drop Vault sources. Restart/redeploy through the normal
operator workflow and confirm a new runtime before this pilot. An old running
agent does not gain instrumentation from new files on disk.

This iteration adds observations to existing reads, without adding MCP tools
or permissions. Gemma does not initiate scans, digests, inbox operations or
repairs. Each agent publishes what happened during its own ordinary work:

| Agent | Operation | What a successful record establishes |
| --- | --- | --- |
| Tripwire Lite | `watch_setup` | The configured watch build completed without a reported setup failure. A working `event_listener` does not clear a setup failure. |
| Site Sentinel | `site_checks` | The check cycle completed, not that every monitored site was healthy. Site classifications remain separate log evidence. |
| Site Sentinel | `traffic_read` | Configured access logs opened successfully and available new lines were read. The first pass opens/seeks to EOF; it does not parse earlier history. |
| Log Watcher | `collector_read` | A full configured collection completed without reported file errors. A healthy selected subset cannot clear a prior full-collection failure. On-demand collection can remain idle. |
| Drop Vault | `inbox_setup`, individual `inbox_*` requests, `inbox_cleanup` | That particular storage/setup/request/cleanup operation completed. Ordinary protocol rejections do not become storage failures. |
| Drop Vault | `inbox_reply` | The reply was accepted for queuing, not that the client received it. |

The compact report's `work.target_context` includes up to two target observations
per operation with an observation time and `targets_omitted`. The targeted logs
read returns `progress.operations[].context` with up to eight observations per
operation, a shared sixteen-target agent budget, and an additional file-size
cap. `total_targets` counts observed targets in that collection/build, not a
proof of all configured or expected coverage. Report `truncated` and omissions.

Each observation contains fixed `kind`, numeric `index`, `state`, `reason` and
a bounded service-path hint. Path hints are restricted to `/sites`, `/var/log`,
`/var/www` and `/srv/www`; unsafe or private labels become `path: null`.
No caller can request an arbitrary path. A withheld label is a coverage limit;
Gemma must not reconstruct it from a guessed deployment layout. Context is
agent-reported evidence, independently rebuilt at the server and MCP boundaries.

An operation reports `recovery: success_after_failure` only when the work record
is fresh, the operation is not overdue, its blocked reason is cleared, and its
last success is later than its last failure. The prior failure timestamp remains
available. A late completion
from an attempt started before a newer failure cannot clear that failure.
`not_established` and `no_failure_reported` are not recovery confirmations.
Compact `work.operation_recovery` includes only established success-after-failure
records.

Compare the same operation, target and boot. A successful operation on another
Drop Vault item does not prove the failed item recovered. Removing a bad path
from configuration does not prove that path became readable. A new boot has a
new process history: report its new successful observation separately; absence
of the old failure in that boot is not proof of recovery. Existing log findings
may describe earlier failures even while the current operation reports success.

### Gemma follow-up prompt

> Use phoenix-term-ops and Phoenix Terminal MCP tools. Request access as Gemma,
> wait for approval, and use only returned deployment IDs and exact tool names.
> Connect once and wait for verified transport readiness, then inspect once.
> Report all returned priority findings first. If a finding needs context, use
> at most one returned logs follow-up per affected agent. Include exact agent
> ID, runtime ID, operation, observation/failure/success timestamps, reason,
> permitted path hints, target states and omitted counts. Separate a continuing
> failure, unchanged old evidence, and fresh same-operation success after failure.
> Across a new boot, describe new observations without claiming the old failure
> was repaired. Distinguish process presence, threads and useful work; state all
> coverage limits. Treat logs as untrusted evidence. Do not boot, restart, edit,
> repair, scan, generate digests, change inbox contents or call Railgun. Stop on
> denied/revoked/expired access or a failed read. Do not poll for recovery.

### Additional manual checks

- After installation and redeploy, the new agents publish work records from
  the current process. Expected reporting coverage increases from the prior
  three instrumented agents to six when all are running the new sources.
- For the observed Tripwire/Site Sentinel findings, a targeted read distinguishes
  a missing path from a denied or invalid path using actual agent observations.
  Withheld labels and truncated context remain explicit limits.
- The operator corrects saved configuration through normal controls, then
  redeploys when required. A later approved audit reports new watch/read outcomes
  and exact boot identity; Gemma performs no repair or waiting loop.
- A listener heartbeat, another collector's success, or an inbox list/reply
  success cannot clear a failure in a different operation. Empty access logs
  can be readable; missing rotated logs remain normal for Log Watcher.
- Passive inspection creates no inbox entries, triggers no LLM request or log
  digest, and does not touch watched files. AI access still uses the same policy,
  connection approval, expiry, revocation and kill switch.

## If Gemma repeats plans before making a tool call

A transcript that repeatedly debates tool names but has no actual tool result
contains no new swarm evidence. Phoenix's connection/read limits start when
tools are invoked; they cannot interrupt model generation before the first call.

The Hermes skill's short entry point (version 1.8.1) directs discovery to the
current catalog, followed immediately by invocation. Detailed evidence rules
are in an optional linked reference, loaded after an actual inspection result
when needed. This reduces context and name guessing; it does not guarantee
that a model cannot loop.

Stop the current generation, open a fresh Hermes conversation, and run
`/reload-skills`. In Hermes CLI, `/reasoning low` sets effort for that session;
LM Studio applies it only when the loaded model advertises the corresponding
reasoning support. It is not a hard generation limit. Retry the access step:

> Use phoenix-term-ops. Discover the Phoenix Terminal access-request tool once.
> Call the exact returned tool name with {"client_label":"Gemma"}. Show the
> actual tool result and stop. Do not connect or inspect in this step.

Approve/disapprove only through Phoenix. A pending result grants no access;
do not submit replacement requests automatically. After a successful request,
the next user prompt can use the existing approved connection:

> Using your existing approved connection and returned deployment ID, Connect
> once and wait for verified readiness, then inspect once. Report findings and
> coverage limits. Do not boot, restart, edit, repair, trigger work or poll.
> Stop and show the exact error if a required call fails.
