"""AI-readable test commands with no live-operation or arbitrary RPC escape hatch."""
import argparse
import json
from pathlib import Path

from .catalog import SECTIONS
from .inventory import inventory
from .runner import run


def main(argv=None):
    parser = argparse.ArgumentParser(description="Phoenix offline process-test terminal (separate from phoenixctl and the GUI)")
    sub = parser.add_subparsers(dest="command", required=True)
    help_parser = sub.add_parser("help", help="Diagnostic contracts, checks and limitations per section")
    help_parser.add_argument("section", nargs="?", choices=sorted(SECTIONS))
    help_parser.add_argument("--json", action="store_true")
    sub.add_parser("inventory", help="JSON dialog/worker candidates and explicit coverage gaps; imports no GUI code")
    for name in ("run", "gate"):
        action = sub.add_parser(name, help="Run offline adapters" if name == "run" else "Pre-public-commit gate: fails on tests, skips AND incomplete parity")
        if name == "run":
            action.add_argument("section", choices=["all", *sorted(SECTIONS)])
        action.add_argument("--timeout", type=int, default=120, help="Per-worker deadline in seconds (1..600)")
        action.add_argument("--report", type=Path, help="Write a NEW JSON report; never overwrite existing files")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.command == "help":
        selected = {args.section: SECTIONS[args.section]} if args.section else SECTIONS
        if args.json:
            print(json.dumps(selected, indent=2))
        else:
            for name, contract in selected.items():
                print(f"\n{name.upper()}\n" + "\n".join(f"{key}: {value}" for key, value in contract.items()))
                print(f"reproduce: python -m phoenix_test_terminal run {name} --report {name}-report.json")
        return 0
    if args.command == "inventory":
        print(json.dumps(inventory(root), indent=2))
        return 0
    if not 1 <= args.timeout <= 600:
        parser.error("timeout must be between 1 and 600 seconds")
    if args.report and args.report.exists():
        parser.error("report already exists; choose a new filename")
    sections = list(SECTIONS) if args.command == "gate" or args.section == "all" else [args.section]
    report = run(root, sections, args.timeout)
    if args.report:
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
    for item in report["results"]:
        if item["status"] != "passed":
            print(f"\n{item['section']}/{item['scenario']}: {item['status']}")
            for error in item.get("errors", []):
                print(error.get("detail", error))
            for skipped in item.get("skipped", []):
                print(f"SKIP IS NOT A PASS: {skipped}")
    readiness = "CERTIFIED" if report["release_ready"] else "NOT CERTIFIED"
    print(f"\nOffline suite: {report['status']}. Full release readiness: {readiness}.")
    if args.command == "gate":
        for gap in report["inventory"]["release_gaps"]:
            print(f"COVERAGE GAP: {gap}")
        return 0 if report["release_ready"] else 2
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
