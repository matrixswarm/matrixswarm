"""Private child entry point. Parent provides a new disposable profile for every run."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import traceback
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--test")
    parser.add_argument("--cockpit-stage", choices=["create", "reopen"])
    parser.add_argument("--registry-stage", choices=["save", "edit", "reopen", "validation", "commit-failure"])
    parser.add_argument("--workspace-stage", choices=["create", "assign", "reopen", "rejection", "graph-failure", "graph-edits", "graph-config", "editor-validation"])
    parser.add_argument("--vault-stage", choices=["create", "opening", "routing", "persist", "reopen", "rotate", "verify-rotation"])
    args = parser.parse_args()
    root, sandbox = args.root.resolve(), args.sandbox.resolve()
    if not (sandbox / ".phoenix-test-only").is_file() or Path.cwd().resolve() != sandbox:
        parser.error("Worker requires an owned test sandbox as working directory")
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root), str(root / "phoenix"), str(root / "phoenix_test_terminal")]
    from phoenix_test_terminal.safety import install_guards
    allowed_child = None
    if args.test == "test_phoenix_startup_policy.py":
        allowed_child = [sys.executable, "-I", "-B", str(root / "phoenix_test_terminal/python_child.py"), str(root), str(sandbox)]
        original_run = subprocess.run

        def guarded_run(command, **kwargs):
            if not isinstance(command, list) or len(command) != 3 or command[:2] != [sys.executable, "-c"]:
                raise PermissionError("Startup adapter only accepts the existing Python test scripts")
            if set(kwargs) - {"capture_output", "check", "env", "text"}:
                raise PermissionError("Unexpected subprocess options")
            from phoenix_test_terminal.runner import child_environment
            environment = child_environment(sandbox)
            if "MATRIXSWARM_PHOENIX_DEBUG" in kwargs.get("env", {}):
                environment["MATRIXSWARM_PHOENIX_DEBUG"] = kwargs["env"]["MATRIXSWARM_PHOENIX_DEBUG"]
            kwargs["env"] = environment
            return original_run(allowed_child, input=command[2], cwd=sandbox, timeout=20, encoding="utf-8", **kwargs)

        subprocess.run = guarded_run
    install_guards(sandbox, allowed_child)
    output = io.StringIO()
    result = {"status": "failed", "tests": 0, "skipped": [], "errors": [], "checks": []}
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            if args.cockpit_stage:
                from phoenix_test_terminal.cockpit_scenario import run
                result["checks"] = run(args.cockpit_stage, sandbox)
                result["tests"] = len(result["checks"])
                result["status"] = "passed"
            elif args.workspace_stage:
                from phoenix_test_terminal.workspace_scenario import run
                result["checks"] = run(args.workspace_stage, sandbox)
                result["tests"] = len(result["checks"])
                result["status"] = "passed"
            elif args.registry_stage:
                from phoenix_test_terminal.registry_scenario import run
                result["checks"] = run(args.registry_stage, sandbox)
                result["tests"] = len(result["checks"])
                result["status"] = "passed"
            elif args.vault_stage:
                if args.vault_stage in {"opening", "routing"}:
                    from phoenix_test_terminal.vault_opening import run
                else:
                    from phoenix_test_terminal.vault_scenario import run
                result["checks"] = run(args.vault_stage, sandbox)
                result["tests"] = len(result["checks"])
                result["status"] = "passed"
            else:
                from phoenix_test_terminal.catalog import SECTIONS
                allowed = {name for section in SECTIONS.values() for name in section["tests"]}
                if args.test not in allowed:
                    raise ValueError("Test is not in the offline adapter allowlist")
                suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern=args.test)
                outcome = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
                result.update(tests=outcome.testsRun, skipped=[{"test": str(t), "reason": r} for t, r in outcome.skipped],
                              errors=[{"test": str(t), "detail": detail} for t, detail in outcome.errors + outcome.failures])
                # Missing dependencies/skips/zero-test suites are never green.
                if outcome.wasSuccessful() and outcome.testsRun > 0 and not outcome.skipped and not outcome.expectedFailures and not outcome.unexpectedSuccesses:
                    result["status"] = "passed"
        except Exception as exc:
            if hasattr(exc, "checks"):
                result["checks"] = exc.checks
                result["tests"] = len(exc.checks) + len(exc.failures)
            result["errors"].append({"detail": traceback.format_exc()})
        finally:
            if args.workspace_stage or args.cockpit_stage:
                # Explicitly tear down the disposable Qt session while Python
                # callbacks and their owning application are still alive.
                from PyQt6 import sip
                from PyQt6.QtWidgets import QApplication
                from PyQt6.QtCore import QCoreApplication, QEvent
                app = QApplication.instance()
                if app is not None:
                    for widget in app.topLevelWidgets():
                        if not sip.isdeleted(widget):
                            sip.delete(widget)
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    sip.delete(app)
    result["log"] = output.getvalue()[-100000:]
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
