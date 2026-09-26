"""Bounded independent interpreters; production vaults and bridge are never loaded."""
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .catalog import SECTIONS
from .inventory import inventory


def child_environment(sandbox):
    # No inherited tokens, SSH agents, Phoenix overrides, PYTHONPATH or vault locations.
    env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "LANG") if name in os.environ}
    env.update({name: str(sandbox) for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "MATRIXSWARM_PATH", "PHOENIX_TERMINAL_DATA_DIR")})
    env.update(QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               PATH=str(Path(sys.executable).parent) + os.pathsep + str(Path(os.environ.get("SystemRoot", "/usr")) / ("System32" if os.name == "nt" else "bin")))
    return env


def invoke(root, sandbox, arguments, timeout):
    started = time.monotonic()
    command = [sys.executable, "-I", "-B", "-X", "faulthandler", str(root / "phoenix_test_terminal/worker.py"),
               "--root", str(root), "--sandbox", str(sandbox), *arguments]
    try:
        process = subprocess.run(command, cwd=sandbox, env=child_environment(sandbox), capture_output=True,
                                 encoding="utf-8", errors="replace", timeout=timeout)
        try:
            result = json.loads(process.stdout)
            if not isinstance(result, dict) or result.get("status") not in {"passed", "failed"}:
                raise ValueError("Invalid worker schema")
            if result["status"] == "passed" and (not isinstance(result.get("tests"), int) or result["tests"] < 1 or result.get("errors") or result.get("skipped")):
                raise ValueError("Invalid pass evidence")
        except (ValueError, TypeError):
            result = {"status": "failed", "errors": [{"detail": "Worker did not return valid JSON"}],
                      "log": (process.stdout + process.stderr)[-100000:]}
        if process.returncode != 0:
            result["status"] = "failed"
            if process.stderr:
                result.setdefault("errors", []).append({"detail": process.stderr[-100000:]})
        result["exit_code"] = process.returncode
    except subprocess.TimeoutExpired:
        result = {"status": "failed", "errors": [{"detail": f"Worker exceeded {timeout}s deadline; terminated"}]}
    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result


def run(root, sections, timeout=120):
    results = []
    for section in sections:
        with tempfile.TemporaryDirectory(prefix="phoenix-test-only-") as temporary:
            sandbox = Path(temporary).resolve()
            (sandbox / ".phoenix-test-only").touch()
            if section == "cold-start":
                jobs = [(stage, ["--cockpit-stage", stage]) for stage in ("create", "reopen")]
            elif section == "vault":
                jobs = [(stage, ["--vault-stage", stage]) for stage in ("create", "opening", "routing", "persist", "reopen", "rotate", "verify-rotation")]
            elif section == "registry-lifecycle":
                jobs = [("create", ["--vault-stage", "create"])] + [(stage, ["--registry-stage", stage]) for stage in ("save", "edit", "reopen", "validation", "commit-failure")]
            elif section == "workspace-lifecycle":
                jobs = [("vault-create", ["--vault-stage", "create"]), ("registry-save", ["--registry-stage", "save"])] + [(stage, ["--workspace-stage", stage]) for stage in ("create", "assign", "reopen", "rejection")]
            elif section == "graph-save":
                jobs = [("vault-create", ["--vault-stage", "create"]), ("create", ["--workspace-stage", "create"]), ("graph-failure", ["--workspace-stage", "graph-failure"]), ("graph-edits", ["--workspace-stage", "graph-edits"]), ("graph-config", ["--workspace-stage", "graph-config"])]
            elif section == "editor-validation":
                jobs = [("vault-create", ["--vault-stage", "create"]), ("validation", ["--workspace-stage", "editor-validation"])]
            else:
                jobs = [(test, ["--test", test]) for test in SECTIONS[section]["tests"]]
            blocked = False
            for name, args in jobs:
                print(f"[{section}] {name} ...", flush=True)
                if blocked:
                    result = {"status": "blocked", "errors": [{"detail": "Earlier vault lifecycle prerequisite failed"}]}
                else:
                    result = invoke(root, sandbox, args, timeout)
                result.update(section=section, scenario=name)
                results.append(result)
                print(f"  {result['status'].upper()}", flush=True)
                if (section in {"cold-start", "vault", "workspace-lifecycle", "graph-save", "editor-validation"} or (section == "registry-lifecycle" and name in {"create", "save", "edit", "reopen"})) and result["status"] != "passed":
                    blocked = True
    discovered = inventory(root)
    passed = bool(results) and all(item["status"] == "passed" for item in results)
    release_ready = (passed and set(sections) == set(SECTIONS) and bool(discovered["surfaces"])
                     and not discovered["parse_errors"] and not discovered["stale_adapters"]
                     and not discovered["release_gaps"]
                     and all(item["coverage"] == "complete-behavioral" for item in discovered["surfaces"]))
    return {"schema_version": 1, "scope": "offline regression adapters, NOT full Phoenix parity",
            "python": sys.version, "platform": platform.platform(),
            "status": "passed" if passed else "failed",
            "results": results, "inventory": discovered,
            "release_ready": release_ready}
