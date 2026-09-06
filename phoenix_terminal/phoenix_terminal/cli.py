"""Command line entry point for Phoenix Terminal."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__
from .catalog import as_jsonable, find
from .bridge_client import call_bridge
from .monitor import add_target, check_target, load_config, record_results, save_config


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

    launch = subparsers.add_parser("launch", help="Launch unmodified Phoenix with the local LLM bridge")
    launch.add_argument("--phoenix-root", type=Path, required=True, help="Existing Phoenix source directory")

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

    bridge = subparsers.add_parser("bridge", help="Call the bridge hosted inside a running Phoenix")
    bridge_sub = bridge.add_subparsers(dest="bridge_command", required=True)
    bridge_sub.add_parser("status", help="Show bridge, vault, and session state")
    bridge_sub.add_parser("deployments", help="List redacted deployments from the unlocked vault")
    bridge_sub.add_parser("sessions", help="List active Phoenix sessions")
    bridge_agents = bridge_sub.add_parser("agents", help="List redacted agents for a deployment")
    bridge_agents.add_argument("deployment_id")
    bridge_tree = bridge_sub.add_parser("tree", help="Read or refresh the live Phoenix agent tree")
    bridge_tree.add_argument("session_id")
    bridge_tree.add_argument("--cached", action="store_true", help="Do not request a refresh")
    bridge_launch = bridge_sub.add_parser("launch", help="Request a deployment session; Phoenix asks the human")
    bridge_launch.add_argument("deployment_id")
    logs_start = bridge_sub.add_parser("logs-start", help="Start a Phoenix-routed agent log subscription")
    logs_start.add_argument("session_id")
    logs_start.add_argument("agent_id")
    logs_start.add_argument("--once", action="store_true", help="Request one response instead of following")
    logs_read = bridge_sub.add_parser("logs-read", help="Read buffered lines from a log subscription")
    logs_read.add_argument("subscription_id")
    logs_read.add_argument("--after", type=int, default=0)
    logs_read.add_argument("--limit", type=int, default=100)
    bridge_call = bridge_sub.add_parser("call", help="Call an allowlisted method with JSON parameters")
    bridge_call.add_argument("method")
    bridge_call.add_argument("--params", default="{}", help="JSON object")
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
    command = args.bridge_command
    if command == "status":
        method, params = "bridge.status", {}
    elif command == "deployments":
        method, params = "deployment.list", {}
    elif command == "sessions":
        method, params = "session.list", {}
    elif command == "agents":
        method, params = "agent.list", {"deployment_id": args.deployment_id}
    elif command == "tree":
        method, params = "agent.tree", {"session_id": args.session_id, "refresh": not args.cached}
    elif command == "launch":
        method, params = "deployment.launch", {"deployment_id": args.deployment_id}
    elif command == "logs-start":
        method, params = "agent.logs.start", {
            "session_id": args.session_id,
            "agent_id": args.agent_id,
            "follow": not args.once,
        }
    elif command == "logs-read":
        method, params = "agent.logs.read", {
            "subscription_id": args.subscription_id,
            "after": args.after,
            "limit": args.limit,
        }
    else:
        method = args.method
        params = json.loads(args.params)
        if not isinstance(params, dict):
            raise ValueError("--params must be a JSON object")
    result = call_bridge(args.data_dir, method, params)
    print(safe_console_text(json.dumps(result, indent=2, ensure_ascii=False)))
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
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
