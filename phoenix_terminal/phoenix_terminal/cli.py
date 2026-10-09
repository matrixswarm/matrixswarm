"""Command line entry point for Phoenix Terminal."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

from .catalog import as_jsonable, find
from .bridge_client import call_bridge
from .monitor import add_target, check_target, load_config, record_results, save_config


try:
    __version__ = package_version("phoenix-terminal")
except PackageNotFoundError:  # Source-tree execution without an installed distribution.
    __version__ = "0.2.0"


def default_data_dir() -> Path:
    override = os.environ.get("PHOENIX_TERMINAL_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "PhoenixTerminal"
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "phoenix-terminal"
    return Path.home() / ".local" / "state" / "phoenix-terminal"


def safe_console_text(value: str) -> str:
    """Avoid failing a read-only inspection in legacy Windows console code pages."""
    encoding = sys.stdout.encoding or "utf-8"
    return value.encode(encoding, errors="replace").decode(encoding)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phoenixctl", description="Phoenix Cockpit terminal companion (safe MVP)")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir(), help="Local terminal state directory")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Read-only Phoenix workspace inspection")
    status.add_argument("--phoenix-root", type=Path, required=True, help="Existing Phoenix source directory")

    launch = subparsers.add_parser("launch", help="Launch the normal Phoenix GUI; no terminal listener or bridge hooks")
    launch.add_argument("--phoenix-root", type=Path, required=True, help="Existing Phoenix source directory")

    vault = subparsers.add_parser("vault", help="Operator-only headless vault inventory; no remote execution")
    vault_sub = vault.add_subparsers(dest="vault_command", required=True)
    vault_open = vault_sub.add_parser("open", help="Prompt privately, select inventory, and enable expiring read-only access",
        description="Open a normal Phoenix password vault in a private operator terminal. Nothing is exposed by default. "
                    "Only public inventory may be shared after explicit selection and confirmation. No vault writes, "
                    "connections, deploys, or credential export. Hardware-factor unlock remains in the GUI.")
    vault_open.add_argument("--phoenix-root", type=Path, required=True, help="Trusted Phoenix source containing its vault crypto")
    vault_open.add_argument("--vault", type=Path, required=True, help="Operator-prepared encrypted vault file (never a password)")

    terminal = subparsers.add_parser(
        "terminal",
        help="Independent operator-approved Terminal connection lifecycle",
    )
    terminal_sub = terminal.add_subparsers(dest="terminal_command", required=True)
    terminal_open = terminal_sub.add_parser(
        "open",
        help="Privately open a prepared Vault and show Terminal-owned approvals",
    )
    terminal_open.add_argument(
        "--phoenix-root", type=Path, required=True, help="Trusted Phoenix source"
    )
    terminal_open.add_argument(
        "--vault", type=Path, required=True, help="Operator-prepared encrypted Vault"
    )
    terminal_request = terminal_sub.add_parser(
        "request", help="Request a connection; the operator must approve it"
    )
    terminal_request.add_argument(
        "--label", required=True, help="Unverified client label shown to the operator"
    )
    terminal_sub.add_parser("status", help="Read endpoint or current request status")
    terminal_sub.add_parser("doctor", help="Diagnose this client's runtime and approval state without requesting access")
    terminal_sub.add_parser("disconnect", help="Revoke this client's connection")
    terminal_alerts = terminal_sub.add_parser(
        "alerts", help="Read an approved deployment's live alert buffer",
        description="Read-only, operator-approved alerts from the exact saved deployment. "
        "Use an ID returned by terminal status after approval. Start with --after 0; "
        "for subsequent pages pass next_cursor as --after and source.stream_id as --stream-id. "
        "Check source.state/code: an empty page is NOT proof of server health. "
        "Only new broadcasts are collected; offline intervals cannot be replayed. "
        "PEER_IDENTITY_FAILED: operator must check the saved CA/pin; never disable TLS. "
        "CONNECTION_FAILED: check the operator's network/VPN and saved endpoint. "
        "PACKET_REJECTED: check deployment keys and clock. Reopen the Vault after corrections.",
    )
    terminal_alerts.add_argument("deployment_id", help="Exact permitted saved deployment ID")
    terminal_alerts.add_argument("--after", type=int, default=0, help="Absolute cursor (default 0)")
    terminal_alerts.add_argument("--limit", type=int, default=100, help="Page size, 1–200")
    terminal_alerts.add_argument("--stream-id", help="source.stream_id returned with the cursor")

    terminal_swarms = terminal_sub.add_parser("swarms", help="One live inventory read on this permitted deployment's fixed SSH server")
    terminal_swarms.add_argument("deployment_id")
    for name in ("agents", "inspect", "sessions", "connect"):
        command = terminal_sub.add_parser(name, help={
            "agents": "Read scoped agent process and heartbeat inventory",
            "inspect": "Read bounded swarm diagnostics (requires agents.list and logs.read)",
            "sessions": "List permitted Phoenix cockpit tabs; not server health",
            "connect": "Open/reuse a Phoenix cockpit tab (does not boot a swarm)",
        }[name])
        command.add_argument("deployment_id", help="Exact ID from approved terminal status")
    terminal_logs = terminal_sub.add_parser("logs", help="Read a bounded current-boot agent log tail")
    terminal_logs.add_argument("deployment_id")
    terminal_logs.add_argument("agent_id", help="Exact agent ID from terminal agents")
    terminal_railgun = terminal_sub.add_parser("railgun", help="Start only an inactive saved universe; no restart or replacement")
    railgun_sub = terminal_railgun.add_subparsers(dest="railgun_command", required=True)
    for name in ("launch", "status"):
        command = railgun_sub.add_parser(name)
        command.add_argument("deployment_id")
        command.add_argument("--operation-id", required=True,
            help="32 lowercase hex characters; retain and REUSE for retries, never generate a fresh ID for an uncertain outcome")

    inspect = subparsers.add_parser("inspect", help="Read Phoenix metadata without executing it")
    inspect_sub = inspect.add_subparsers(dest="inspect_command", required=True)
    agents = inspect_sub.add_parser("agents", help="List bundled agent metadata")
    agents.add_argument("--phoenix-root", type=Path, required=True, help="Existing Phoenix source directory")
    templates = inspect_sub.add_parser("templates", help="List directive templates without loading them")
    templates.add_argument("--phoenix-root", type=Path, required=True, help="Existing Phoenix source directory")

    catalog = subparsers.add_parser("catalog", help="Describe commands for people and AI assistants")
    catalog.add_argument("name", nargs="?", help="Optional command name")
    catalog.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    monitor = subparsers.add_parser("monitor", help="Opt-in HTTP/HTTPS uptime monitor")
    monitor_sub = monitor.add_subparsers(dest="monitor_command", required=True)
    monitor_sub.add_parser("init", help="Create an empty monitor configuration")
    add = monitor_sub.add_parser("add", help="Add an authorized endpoint")
    add.add_argument("name")
    add.add_argument("url")
    add.add_argument("--expect-status", type=int, default=200)
    monitor_sub.add_parser("list", help="List configured endpoints")
    check = monitor_sub.add_parser("check", help="Check each endpoint once")
    check.add_argument("--timeout", type=float, default=10.0)
    watch = monitor_sub.add_parser("watch", help="Continuously check configured endpoints")
    watch.add_argument("--interval", type=float, default=60.0)
    watch.add_argument("--timeout", type=float, default=10.0)

    bridge = subparsers.add_parser("bridge", help="Call the headless terminal endpoint (inventory only)",
        description="Only describe, status, deployments, agents and agent are currently supported. "
                    "Legacy operational commands are retained for compatibility but unavailable. "
                    "No command opens a GUI approval dialog or grants authority.")
    bridge_sub = bridge.add_subparsers(dest="bridge_command", required=True)
    bridge_sub.add_parser("describe", help="Discover exact operation schemas and approval hints")
    bridge_sub.add_parser("status", help="Show headless assignment state and expiry")
    bridge_sub.add_parser("deployments", help="List redacted deployments from the unlocked vault")
    bridge_sub.add_parser("sessions", help="Legacy GUI operation (unavailable)")
    bridge_agents = bridge_sub.add_parser("agents", help="List redacted agents for a deployment")
    bridge_agents.add_argument("deployment_id")
    bridge_tree = bridge_sub.add_parser("tree", help="Legacy GUI operation (unavailable)")
    bridge_tree.add_argument("session_id")
    bridge_tree.add_argument("--cached", action="store_true", help="Do not request a refresh")
    bridge_launch = bridge_sub.add_parser("launch", help="Legacy GUI operation (unavailable)")
    bridge_launch.add_argument("deployment_id")
    bridge_launch.add_argument("--request-id", default=None, help="Reuse this ID to avoid duplicate action requests")
    logs_start = bridge_sub.add_parser("logs-start", help="Legacy GUI operation (unavailable)")
    logs_start.add_argument("session_id")
    logs_start.add_argument("agent_id")
    logs_start.add_argument("--once", action="store_true", help="Request one response instead of following")
    logs_read = bridge_sub.add_parser("logs-read", help="Legacy GUI operation (unavailable)")
    logs_read.add_argument("subscription_id")
    logs_read.add_argument("--after", type=int, default=0)
    logs_read.add_argument("--limit", type=int, default=100)
    describe = bridge_sub.add_parser("agent", help="Read one saved agent's public identity; no configuration")
    describe.add_argument("deployment_id")
    describe.add_argument("agent_id")
    settings = bridge_sub.add_parser("config-set", help="Legacy GUI operation (unavailable)")
    settings.add_argument("deployment_id")
    settings.add_argument("agent_id")
    settings.add_argument("--changes", required=True, help='JSON object, e.g. {"poll_interval": 5}')
    settings.add_argument("--request-id", default=None)
    restart = bridge_sub.add_parser("restart", help="Legacy GUI operation (unavailable)")
    restart.add_argument("session_id")
    restart.add_argument("agent_id")
    restart.add_argument("--request-id", default=None)
    action = bridge_sub.add_parser("action", help="Legacy GUI operation (unavailable)")
    action.add_argument("request_id")
    alerts = bridge_sub.add_parser("alerts", help="Legacy GUI operation (unavailable)")
    alerts.add_argument("session_id")
    alerts.add_argument("--after", type=int, default=0)
    alerts.add_argument("--limit", type=int, default=100)
    bridge_call = bridge_sub.add_parser("call", help="Call an allowlisted method with JSON parameters")
    bridge_call.add_argument("method")
    bridge_call.add_argument("--params", default="{}", help="JSON object")
    investigation = subparsers.add_parser("investigation", help="Legacy GUI prototype; unavailable in headless inventory mode")
    investigations = investigation.add_subparsers(dest="investigation_command", required=True)
    investigations.add_parser("list", help="List saved selections within the current assignment")
    opened = investigations.add_parser("open", help="Save a fixed deployment/agent selection; no remote action")
    opened.add_argument("investigation_id")
    opened.add_argument("deployment_id")
    opened.add_argument("agent_id")
    resumed = investigations.add_parser("resume", help="Show selection, review positions, and missing evidence windows")
    resumed.add_argument("investigation_id")
    attached = investigations.add_parser("attach", help="Start reviewing one running session; does not connect or deploy")
    attached.add_argument("investigation_id")
    attached.add_argument("session_id")
    attached.add_argument("--reset", action="store_true", help="Acknowledge lost buffers and start a new review window")
    reviewed = investigations.add_parser("read", help="Read evidence without advancing the saved position")
    reviewed.add_argument("investigation_id")
    reviewed.add_argument("stream", choices=("logs", "alerts"))
    reviewed.add_argument("--limit", type=int, default=100)
    acknowledged = investigations.add_parser("ack", help="Save a reviewed page's receipt in the encrypted Phoenix vault")
    acknowledged.add_argument("investigation_id")
    acknowledged.add_argument("receipt")
    mcp = subparsers.add_parser("mcp", help="Run the native Phoenix MCP adapter over stdio")
    mcp.add_argument("--terminal-access", action="store_true", help="Use approved alerts, diagnostics, cockpit session and guarded Railgun tools")
    return parser


def workspace_status(root: Path) -> int:
    expected = ("phoenix.py", "matrix_gui", "README.md")
    missing = [name for name in expected if not (root / name).exists()]
    print(f"Phoenix source: {root.resolve()}")
    if missing:
        print("Status: not recognized (missing: " + ", ".join(missing) + ")")
        return 2
    py_files = sum(1 for _ in root.rglob("*.py"))
    print("Status: recognized, read-only inspection")
    print(f"Python files: {py_files}")
    print("Remote operations: not enabled in this MVP")
    return 0


def recognized_workspace(root: Path) -> bool:
    return all((root / name).exists() for name in ("phoenix.py", "matrix_gui", "README.md"))


def inspect_agents(root: Path) -> int:
    if not recognized_workspace(root):
        print("Error: Phoenix root is not recognized.", file=sys.stderr)
        return 2
    entries = []
    for metadata_path in sorted((root / "agents_meta").glob("*.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"WARN {metadata_path.name}: invalid JSON ({exc.msg})", file=sys.stderr)
            continue
        ui = metadata.get("config", {}).get("ui", {}).get("agent_tree", {})
        entries.append((metadata.get("name", metadata_path.stem), metadata.get("universal_id", "-"), ui.get("emoji", "")))
    print(f"Bundled agents: {len(entries)} (metadata only; no agent code was executed)")
    for name, universal_id, emoji in entries:
        print(safe_console_text(f"{emoji:2} {name:28} {universal_id}"))
    return 0


def inspect_templates(root: Path) -> int:
    if not recognized_workspace(root):
        print("Error: Phoenix root is not recognized.", file=sys.stderr)
        return 2
    templates = sorted((root / "boot_directives").glob("*.py"))
    print(f"Directive templates: {len(templates)} (listed only; no Python was executed)")
    for template in templates:
        print(f"{template.name:32} {template.stat().st_size} bytes")
    return 0


def print_results(results: list[object]) -> int:
    failed = False
    for result in results:
        state = "UP" if result.ok else "DOWN"
        detail = f"HTTP {result.status}" if result.status is not None else result.error or "unknown error"
        print(f"{state:4} {result.name:20} {detail:24} {result.latency_ms}ms  {result.url}")
        failed = failed or not result.ok
    return 1 if failed else 0


def run_monitor(args: argparse.Namespace) -> int:
    if args.monitor_command == "init":
        if args.data_dir.joinpath("monitors.json").exists():
            print("Monitor configuration already exists; no changes made.")
        else:
            save_config(args.data_dir, {"version": 1, "targets": []})
            print(f"Created {args.data_dir / 'monitors.json'}")
        return 0
    if args.monitor_command == "add":
        add_target(args.data_dir, args.name, args.url, args.expect_status)
        print(f"Added monitor '{args.name}' (URL is stored locally).")
        return 0
    config = load_config(args.data_dir)
    if args.monitor_command == "list":
        if not config["targets"]:
            print("No endpoints configured. Run: phoenixctl monitor add <name> <https-url>")
        for target in config["targets"]:
            print(f"{target['name']:20} expects HTTP {target['expected_status']}  {target['url']}")
        return 0
    if not config["targets"]:
        print("No endpoints configured.", file=sys.stderr)
        return 2
    while True:
        results = [check_target(target, args.timeout) for target in config["targets"]]
        record_results(args.data_dir, results)
        exit_code = print_results(results)
        if args.monitor_command == "check":
            return exit_code
        print(f"Next check in {args.interval:g}s. Press Ctrl+C to stop.")
        time.sleep(args.interval)


def run_bridge(args: argparse.Namespace) -> int:
    from .vault_console import READ_OPERATIONS

    command = args.bridge_command
    simple = {"describe": "tools.describe", "status": "bridge.status", "deployments": "deployment.list"}
    if command in simple:
        method, params = simple[command], {}
    elif command == "agents":
        method, params = "agent.list", {"deployment_id": args.deployment_id}
    elif command == "agent":
        method, params = "agent.describe", {"deployment_id": args.deployment_id, "agent_id": args.agent_id}
    elif command == "call":
        method, params = args.method, json.loads(args.params)
        if not isinstance(params, dict):
            raise ValueError("--params must be a JSON object")
    else:
        raise ValueError("Unavailable: the GUI bridge has been retired. The headless terminal currently exposes inventory only.")
    if method not in READ_OPERATIONS:
        raise ValueError("Unavailable in headless inventory mode. No GUI bridge operations or remote actions are enabled.")
    result = call_bridge(args.data_dir, method, params)
    print(safe_console_text(json.dumps(result, indent=2, ensure_ascii=False)))
    return 0


def run_investigation(args: argparse.Namespace) -> int:
    raise ValueError("Unavailable: GUI investigation hooks were retired. A standalone terminal evidence adapter is not implemented.")


def run_terminal_command(args: argparse.Namespace) -> int:
    if args.terminal_command == "doctor":
        from .client_setup import diagnose

        result = diagnose(args.data_dir)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if result["code"] in {"APPROVED", "AWAITING_APPROVAL", "REQUEST_REQUIRED"} else 2
    if args.terminal_command == "open":
        from .terminal_runtime import run_terminal

        return run_terminal(args.phoenix_root, args.vault, args.data_dir)

    from .terminal_client import TerminalClientIdentity, call_terminal

    identity = TerminalClientIdentity(args.data_dir)
    if args.terminal_command == "request":
        result = identity.request(args.label)
    elif args.terminal_command == "disconnect":
        result = identity.disconnect()
    elif args.terminal_command == "alerts":
        result = identity.read_alerts(args.deployment_id, after=args.after,
                                      limit=args.limit, stream_id=args.stream_id)
    elif args.terminal_command == "swarms":
        result = identity.list_swarms(args.deployment_id)
    elif args.terminal_command == "agents":
        result = identity.list_agents(args.deployment_id)
    elif args.terminal_command == "logs":
        result = identity.read_logs(args.deployment_id, args.agent_id)
    elif args.terminal_command == "inspect":
        result = identity.inspect_swarm(args.deployment_id)
    elif args.terminal_command == "sessions":
        result = identity.list_sessions(args.deployment_id)
    elif args.terminal_command == "connect":
        result = identity.open_session(args.deployment_id)
    elif args.terminal_command == "railgun":
        operation = identity.launch_railgun if args.railgun_command == "launch" else identity.railgun_status
        result = operation(args.deployment_id, args.operation_id)
    elif identity.path.is_file():
        result = identity.status()
    else:
        result = call_terminal(args.data_dir, "terminal.status", {})
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return workspace_status(args.phoenix_root)
        if args.command == "launch":
            from .bridge.launcher import launch
            return launch(args.phoenix_root, args.data_dir)
        if args.command == "vault":
            from .vault_console import run_console
            return run_console(args.phoenix_root, args.vault, args.data_dir)
        if args.command == "terminal":
            return run_terminal_command(args)
        if args.command == "inspect":
            if args.inspect_command == "agents":
                return inspect_agents(args.phoenix_root)
            if args.inspect_command == "templates":
                return inspect_templates(args.phoenix_root)
        if args.command == "catalog":
            if args.name is None:
                commands = as_jsonable()
            else:
                command = find(args.name)
                commands = [] if command is None else [command.__dict__]
            if not commands:
                parser.error(f"Unknown command: {args.name}")
            if args.json:
                print(json.dumps(commands, indent=2))
            else:
                for command in commands:
                    print(f"{command['name']}: {command['purpose']}")
                    print(f"  State: {command['state']}; risk: {command['risk']}; dry run: {command['supports_dry_run']}")
                    print("  Prerequisites: " + ", ".join(command["prerequisites"]))
            return 0
        if args.command == "monitor":
            return run_monitor(args)
        if args.command == "bridge":
            return run_bridge(args)
        if args.command == "investigation":
            return run_investigation(args)
        if args.command == "mcp":
            from .mcp_server import main as run_mcp
            return run_mcp(args.data_dir, terminal_access=args.terminal_access)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
