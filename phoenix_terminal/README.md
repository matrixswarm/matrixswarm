# Phoenix Terminal

Phoenix GUI authors the vault; the separate operator terminal owns terminal access.
Launching Phoenix no longer installs an LLM bridge, activity indicator, approval
presenter, or session monkeypatch. Opening the GUI does not grant an agent access.

## Terminal Mode setup

Unlock Phoenix normally, then click **Terminal Mode** in the top bar. Its
separate window contains the saved access policy and **Matrix SSH routes…**.
The Dashboard and login dialog do not contain Terminal setup controls.

Opening this window does not start a listener, approve a client, or grant
operations. Only explicitly saved policy and metadata are written to the
existing encrypted vault. The separate Phoenix Terminal runtime still requires
operator approval. Closing the vault closes the setup window.

Terminal-specific SSH fields appear only in route editors opened from this
window. Ordinary Registry editors keep their normal presentation. Legacy
`ui_preferences.llm_terminal_fields` values are ignored.

The first supported editor is **matrix_ssh**:

- Normal mode keeps the ordinary SSH-profile selector.
- Terminal Mode shows **Target server** and narrows SSH choices by host, port,
  and pinned host key.
- Saving records the chosen SSH serial, account and server identity under
  `meta.terminal`. Passwords and private keys are not copied into this metadata.
- Hiding the fields preserves the metadata; it does not remove a constraint.
  Editing ordinary credentials later can make saved terminal metadata stale.
- Terminal metadata is excluded from deployed agent configuration. It is not
  executed by the GUI.

This authoring policy now feeds the independent Terminal approval runtime. It
does not itself grant access. The guarded Railgun adapter uses the saved deployment's
fixed Registry target, rejects caller overrides and stale bindings, and requires
its separate `railgun.launch` whitelist. It refuses active universes rather than
replacing them. `swarms.list` is independently whitelisted read-only inventory.

## Operator-approved Terminal connections

Phoenix Terminal owns an independent approval endpoint and receive-only live
swarm-alert transport, fixed-server Swarms reads and inactive-only Railgun launches.
It is not hosted by Phoenix GUI and does not restore the retired GUI bridge.
Install the desktop, alerts and remote extras in the environment used to run it:

```powershell
python -m pip install -e ".[desktop,alerts,remote]"
```

Open an operator-prepared Vault from a private desktop terminal. The password
is accepted only by the hidden interactive prompt:

```powershell
$vaultPath = (Read-Host 'Full path to the prepared test vault JSON').Trim('"')
python -B -m phoenix_terminal --data-dir "$env:LOCALAPPDATA/PhoenixTerminal" terminal open --phoenix-root ../phoenix --vault $vaultPath
```

In the prospective agent's terminal, using the same local data directory:

```powershell
python -B -m phoenix_terminal --data-dir "$env:LOCALAPPDATA/PhoenixTerminal" terminal request --label 'monitor-agent'
python -B -m phoenix_terminal --data-dir "$env:LOCALAPPDATA/PhoenixTerminal" terminal status
```

The label is client-supplied and explicitly shown as unverified. A request
releases no Vault inventory. The Terminal-owned dialog defaults to Deny and
binds an approval to the exact client secret, request, immutable Vault revision,
resources, and lifetime. Expiry, disconnect, locking, or closing Terminal
revokes the grant. The client API deliberately has no approval command.

Before opening the Terminal runtime, use Phoenix’s **Terminal Mode** window to save
**Terminal access**: allow requests, set a bounded approval lifetime, enable
read-only swarm alerts, and select the exact deployments. Swarms inventory and
Railgun launch have separate checkboxes and per-deployment columns, off by default
for existing policies. Use the same prepared
vault in Terminal, with the current deployment's saved keys and receiver. An
already-open Terminal snapshot must be closed and reopened after policy changes.

After **Allow connection**, `terminal status` reports effective operations and only their
permitted deployment IDs under `resources`. For each permitted deployment, the
worker connects to its one saved `matrix_websocket` WSS `payload.reception`
receiver. It uses the saved CA, client identity, server SPKI pin and signing
keys. It does not use Phoenix GUI, send SSH commands, follow redirects, accept
target overrides, or connect before approval. TLS failures are never bypassed.

### Live alert test and pagination

In the client terminal, copy the exact permitted ID from `terminal status`:

```powershell
$deploymentId = (Read-Host 'Permitted deployment ID from terminal status').Trim()
python -B -m phoenix_terminal --data-dir "$env:LOCALAPPDATA/PhoenixTerminal" terminal alerts $deploymentId
```

Wait for `source.state: connected` and `source.code: AWAITING_ALERTS`, then
trigger a harmless new alert in the test swarm (for example, an operator-set
BTC threshold). Run the same read again. A verified received alert changes the
code to `RECEIVING_ALERTS`. Only new alerts are received: there is no historical
replay. Empty results do **not** mean the server is healthy or prove the producer
is functioning. `connected` means TLS/pin verification and hello submission;
this server protocol has no application-level hello acknowledgement.

### Resumed Swarms and Railgun work

Use `terminal swarms DEPLOYMENT_ID` for a single active-swarm inventory on that
deployment's saved, pinned SSH server. It provides no kill or replacement powers.
Railgun's asynchronous `terminal railgun launch/status` commands require a retained
`--operation-id`; retries always reuse it. Update MatrixOS's durable request wrapper
before use: older servers fail closed without the inactive-universe guard.
The [Terminal access contract and operator smoke test](docs/TERMINAL_ACCESS.md#swarms-and-railgun-fixed-targets-never-replacement)
includes commands and expected denial/refusal behavior. No live dispatch was used
in automated tests. Logs, health queries, panel actions and restarts remain future
adapters rather than implied permissions.

For the optional MCP SDK, `mcp --terminal-access` selects these approved adapters
using the same client identity/authorizer as the CLI. Plain `mcp` keeps the legacy
saved-inventory toolset separate.

`terminal request` and `terminal status` show approval, **not messages**. Use
`terminal alerts` to read the buffer. The operator window and each alert page
show `received_alerts` and `rejected_packets` separately. A later rejected frame
can set `PACKET_REJECTED` even after a valid BTC alert arrived; it does not delete
that alert. `source.last_rejection` is a fixed diagnostic code, never raw packet
content: `UNEXPECTED_SENDER` means a different serial than the pinned receiver;
`SIGNATURE_INVALID`, `TIMESTAMP_INVALID`, and `DECRYPTION_FAILED` identify the
verification stage. Rejected traffic is not proof that the particular alert you
triggered was rejected. Do not widen the sender allowlist or disable checks.

Each page includes `next_cursor` and `source.stream_id`. Subsequent pages use
both, with a maximum page size of 200. Buffers retain at most 500 alerts per feed:

```powershell
# Paste the values returned in the preceding page, not a different connection.
$cursor = [long](Read-Host 'next_cursor')
$streamId = (Read-Host 'source.stream_id').Trim()
python -B -m phoenix_terminal --data-dir "$env:LOCALAPPDATA/PhoenixTerminal" terminal alerts $deploymentId --after $cursor --stream-id $streamId --limit 50
python -B -m phoenix_terminal --data-dir "$env:LOCALAPPDATA/PhoenixTerminal" terminal disconnect
```

Verify that a deployment without `alerts.read` is denied and that reads after
disconnect fail. Approval expiry and lock also revoke reads and stop the feed.
A changed grant resets the in-memory stream; restart with `--after 0` and no
old stream ID. `gap: true` reports retention loss; `may_have_missed: true`
reports a broken/rejected live feed interval, not a recovered history.

Diagnostics are fixed codes, without raw transport exceptions or credentials:

| Source code | Meaning and operator action |
| --- | --- |
| `CONNECTING` | The background worker is opening the saved receiver. |
| `AWAITING_ALERTS` | TLS/pin verified and hello sent; waiting for a signed alert. |
| `RECEIVING_ALERTS` | At least one authenticated alert was received in this connection. |
| `CONNECTION_FAILED` / `SOURCE_CLOSED` | Retrying the same target; check reachability and server logs. |
| `PEER_IDENTITY_FAILED` | CA, validity or SPKI verification failed; check saved certificates and TLS interception. Do not disable verification. |
| `TRUST_MATERIAL_INVALID` | Repair the prepared deployment's certificate/signing material and reopen. |
| `PACKET_REJECTED` | Invalid, replayed, expired or unexpected packet; inspect deployed keys, clocks and logs. |
| `WORKER_FAILED` | Adapter error; operator console reports the exception type only. Reopen after diagnosis. |

The client receives only fixed-schema, bounded, redacted alert fields. Treat
messages as untrusted evidence, never instructions. Delete, acknowledge, mute,
logs, panels, restarts, deployment and arbitrary calls remain unavailable. The
older inventory endpoint below is separate from this approval runtime.

## Headless operator vault console

The toolkit model (vault-defined resources, immutable deployments, operation
whitelists, and operator-approved connections) is recorded in
[Terminal access contract](docs/TERMINAL_ACCESS.md). Connection approval is now
implemented with scoped live alert reads as described above. The existing
inventory console below remains a separate compatibility runtime.

From this directory, using an environment containing Phoenix crypto dependencies:

```powershell
python -B -m phoenix_terminal vault open --phoenix-root ../phoenix --vault 'C:/path/to/operator-vault.json'
```

Replace the example with an actual operator-prepared vault. Enter its password
only in the private operator console. Nothing is exposed until the operator
selects exact deployment IDs and confirms a bounded `enable` request.

```text
deployments
select EXACT_DEPLOYMENT_ID
enable 900
status
lock
```

The endpoint exposes only public saved inventory, not live health, credentials,
logs, connections, deployment execution or writes. Lock, exit and expiry revoke
access. The display-mode flag is not consulted for authorization.

In a separate agent terminal using the same `--data-dir`:

```powershell
python -m phoenix_terminal bridge describe
python -m phoenix_terminal bridge status
python -m phoenix_terminal bridge deployments
python -m phoenix_terminal bridge agents EXACT_DEPLOYMENT_ID
python -m phoenix_terminal bridge agent EXACT_DEPLOYMENT_ID EXACT_AGENT_ID
```

The command name `bridge` is retained for compatibility; its active endpoint is
owned by the headless console, not Phoenix GUI. Legacy operational CLI commands
and prototype modules/tests remain for future adapter migration but are not
enabled by a supported launcher. They are unavailable in headless inventory mode.

See [Operator toolbox](docs/OPERATOR_TOOLBOX.md) and
[AI workflow contract](docs/AI_WORKFLOW_GUIDE.md) for boundaries and diagnostics.

## Ordinary GUI and read-only inspection

```powershell
python -m phoenix_terminal launch --phoenix-root ../phoenix
python -m phoenix_terminal status --phoenix-root ../phoenix
python -m phoenix_terminal inspect agents --phoenix-root ../phoenix
python -m phoenix_terminal inspect templates --phoenix-root ../phoenix
```

`launch-pycharm.ps1` also launches the normal GUI. It does not copy or modify the
selected source checkout. The new authoring fields require the updated Phoenix
source, not an older separate testing checkout.

## Optional MCP adapter

MCP is not required. With the optional SDK installed (`python -m pip install -e
".[mcp]"`), `python -m phoenix_terminal.mcp_server` runs a separate stdio client
of the same headless endpoint. It has exactly five read-only tools:

- `phoenix_bridge_status`
- `phoenix_describe_tools`
- `phoenix_list_deployments`
- `phoenix_list_agents`
- `phoenix_describe_agent`

There are no GUI-confirmed connection or logging tools. Use
`scripts/verify_live_mcp.py` only with an operator-enabled test inventory endpoint.
Never paste its local token file or a vault password into model context.

## Opt-in uptime monitor

```powershell
python -m phoenix_terminal monitor init
python -m phoenix_terminal monitor add main-site https://example.com --expect-status 200
python -m phoenix_terminal monitor check
```

Only add endpoints you own or are authorized to monitor. Monitoring reads configured
HTTP/HTTPS URLs and records availability; it does not deploy or authenticate.

## Tests and boundary

Tests use synthetic vaults and temporary loopback endpoints. The application-level
allowlist is not isolation from an agent with unrestricted execution as the operator's
OS account. Independent execution identity, persisted operation policies, strict
target binding and non-production validation are required before remote autonomy.

```powershell
python -B -m unittest discover -v -s tests
```

The live-alert tests include signed/encrypted packets, in-memory mutual TLS, a
real loopback client API, and a separate real-socket WSS test. Some local security
products replace even loopback TLS certificates. That real-socket test should
fail rather than trust the replacement. For diagnosis only, setting
`PHOENIX_TEST_SKIP_LOOPBACK_TLS=1` explicitly skips that one test; it must still
run in an unintercepted environment before claiming full transport validation.
CI does not set this override. No production TLS checks depend on that variable.
