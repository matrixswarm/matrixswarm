# Phoenix Terminal

`phoenixctl` is a separate, terminal-first companion to Phoenix Cockpit. It does not edit or overwrite the `phoenix/` source tree; the opt-in launcher imports Phoenix at runtime and attaches narrow bridge hooks in memory.

The first release establishes three things:

1. a read-only inspector for a Phoenix workspace; and
2. opt-in HTTP/HTTPS uptime monitoring for sites you own or are authorized to monitor; and
3. a session-scoped, operator-enabled bridge into a running Phoenix Cockpit.

It also includes the first Phoenix Bridge implementation. The bridge is loaded into the Phoenix process by a separate launcher, while the original `phoenix/` tree remains unchanged. Phoenix continues to own the vault, connections, packet signing, encryption, and agent communication.

Phoenix parity is developed as verified adapters, not as blind shell execution. Connecting a deployment through the bridge requires an explicit Phoenix confirmation; broader remote actions remain unavailable until their protocol, vault, and authorization contracts have tests.

## Quick start

```powershell
cd .\phoenix_terminal
python -m phoenix_terminal status --phoenix-root ..\phoenix
python -m phoenix_terminal inspect agents --phoenix-root ..\phoenix
python -m phoenix_terminal inspect templates --phoenix-root ..\phoenix
python -m phoenix_terminal monitor init
python -m phoenix_terminal monitor add main-site https://example.com --expect-status 200
python -m phoenix_terminal monitor check
```

## Phoenix Bridge

Launch the normal Phoenix GUI with bridge support attached:

```powershell
python -m phoenix_terminal launch --phoenix-root ..\phoenix
```

On Windows, the launcher automatically uses the sibling `phoenix` directory and its `.venv` when present:

```powershell
.\launch-pycharm.ps1
```

If Windows requires locally created PowerShell scripts to be signed, keep that policy in place and invoke the module directly:

```powershell
$py = 'C:\path\to\phoenix_gui\.venv\Scripts\python.exe'
$phoenixRoot = (Resolve-Path '..\phoenix').Path
& $py -m phoenix_terminal launch --phoenix-root $phoenixRoot
```

To test against a separate PyCharm checkout, pass both paths explicitly or set the `PHOENIX_ROOT` and `PHOENIX_PYTHON` environment variables:

```powershell
.\launch-pycharm.ps1 -PhoenixRoot 'D:\workspace\phoenix_gui' `
    -PythonPath 'D:\workspace\phoenix_gui\.venv\Scripts\python.exe'
```

The launcher does not copy, edit, stage, commit, or push anything in the selected Phoenix working copy.

The bridge starts **OFF**. Unlock a vault in Phoenix exactly as usual, then choose **LLM Bridge → Enable LLM Bridge…** and confirm. From another terminal, the bridge can then be queried:

```powershell
python -m phoenix_terminal bridge status
python -m phoenix_terminal bridge deployments
python -m phoenix_terminal bridge agents phoenix
python -m phoenix_terminal bridge launch phoenix
python -m phoenix_terminal bridge sessions
python -m phoenix_terminal bridge tree phoenix
python -m phoenix_terminal bridge logs-start phoenix matrix
python -m phoenix_terminal bridge logs-read SUBSCRIPTION_ID_FROM_LOGS_START
```

`logs-start` returns a temporary `subscription_id` for that one log stream. It is distinct from the deployment ID and live Phoenix session ID. Pass the returned value to `logs-read`; disabling the bridge, locking the vault, or closing Phoenix revokes it.

`bridge launch` opens a Phoenix deployment connection session; it does not run `matrixd boot`. Phoenix displays a human confirmation dialog before opening the session. Agent log requests are routed through the active Phoenix session and its existing `cmd_service_request`, signing, encryption, and connector pipeline.

Turning the bridge off stops its loopback listener, deletes its connection/token file, and revokes all log subscriptions. Closing the vault or Phoenix forces the bridge off. Every enable generates a new random token; reopening a vault never re-enables the bridge automatically. Launching Phoenix directly with `python phoenix.py` does not load any bridge code.

Only one Phoenix LLM Bridge can be enabled per Windows user profile. Opening another Phoenix window does not disturb the active endpoint; attempting to enable its bridge reports which existing Phoenix process owns the endpoint and leaves that endpoint intact.

The Phoenix status bar provides an activity LED for the current application session: gray **OFF**, green **ON**, and amber **ACTIVE** whenever an authenticated LLM request crosses the bridge. The attachment permission and token exist only for that Phoenix run.

`monitor watch --interval 60` continuously checks the configured public endpoints. It does not authenticate, crawl, submit forms, or modify remote systems.

## Safety model

- Monitoring is opt-in and only checks URLs in this project's local config.
- Output redacts URL credentials and query values.
- Vault contents and connection material are never returned. Log output receives conservative secret-label, private-key, token, credential, and URL-credential redaction before crossing the bridge.
- Operators should still prevent agents from logging unlabeled secret material; no pattern-based log sanitizer can classify arbitrary plaintext perfectly.
- Future deploy, agent, and Railgun commands will require explicit confirmation, a dry run, and a verified adapter.

## Roadmap

The command catalog already describes the target surface: vaults, connections, directives, deployments, swarm lifecycle, agents, Railgun, logs, and health. The implementation order is read-only inspection, validation/dry-run, then controlled write operations.
