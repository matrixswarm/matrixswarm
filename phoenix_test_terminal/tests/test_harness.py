import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from phoenix_test_terminal.__main__ import main
from phoenix_test_terminal.catalog import SECTIONS
from phoenix_test_terminal.inventory import inventory
from phoenix_test_terminal.runner import child_environment, invoke, run

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


class HarnessTests(unittest.TestCase):
    def test_help_has_diagnostic_contract_for_every_section(self):
        for section in SECTIONS.values():
            for field in ("purpose", "checks", "diagnose", "limits"):
                self.assertTrue(section[field])
            for filename in section["tests"]:
                self.assertTrue((REPO / "tests" / filename).is_file())

    def test_help_is_machine_readable_and_does_not_import_gui(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, main(["help", "vault", "--json"]))
        self.assertEqual(["vault"], list(json.loads(output.getvalue())))

    def test_inventory_finds_new_dialog_and_parse_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "phoenix").mkdir()
            (root / "phoenix/new.py").write_text("class NewDialog(QDialog):\n def accept(self): pass\n")
            (root / "phoenix/bad.py").write_text("class ???")
            report = inventory(root)
            self.assertEqual("unmapped", report["surfaces"][0]["coverage"])
            self.assertEqual(["accept"], report["surfaces"][0]["methods"])
            self.assertEqual(1, len(report["parse_errors"]))
            self.assertTrue(report["stale_adapters"])

    def test_real_inventory_has_no_stale_claims(self):
        result = inventory(REPO)
        self.assertFalse(result["stale_adapters"])
        self.assertGreater(len(result["surfaces"]), 4)
        self.assertTrue(result["release_gaps"])

    def test_inventory_includes_indirect_config_editors_without_claiming_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "phoenix").mkdir()
            (root / "phoenix/editor.py").write_text("class Example(BaseEditor):\n def _save(self): pass\n")
            result = inventory(root)
            self.assertEqual(len(result["surfaces"]), 1)
            self.assertEqual(result["surfaces"][0]["coverage"], "unmapped")
            self.assertIsNone(result["surfaces"][0]["adapter"])

    def test_environment_has_no_user_credentials(self):
        with patch.dict(os.environ, {"TELEGRAM_TOKEN": "secret", "SSH_AUTH_SOCK": "agent", "PYTHONPATH": "unsafe", "MATRIXSWARM_PATH": "live"}):
            env = child_environment(Path("test-sandbox"))
        for name in ("TELEGRAM_TOKEN", "SSH_AUTH_SOCK", "PYTHONPATH"):
            self.assertNotIn(name, env)
        self.assertEqual("test-sandbox", env["HOME"])
        self.assertEqual("test-sandbox", env["MATRIXSWARM_PATH"])
        self.assertEqual("offscreen", env["QT_QPA_PLATFORM"])

    def test_failed_vault_stage_blocks_remaining_lifecycle(self):
        with patch("phoenix_test_terminal.runner.invoke", return_value={"status": "failed"}) as child, contextlib.redirect_stdout(io.StringIO()):
            result = run(REPO, ["vault"])
        self.assertEqual(1, child.call_count)
        self.assertEqual(["failed"] + ["blocked"] * 6, [item["status"] for item in result["results"]])
        self.assertFalse(result["release_ready"])

    def test_empty_run_does_not_pass(self):
        self.assertEqual("failed", run(REPO, [])["status"])

    def test_registry_prerequisite_failure_blocks_dependents(self):
        with patch("phoenix_test_terminal.runner.invoke", return_value={"status": "failed"}) as child, contextlib.redirect_stdout(io.StringIO()):
            result = run(REPO, ["registry-lifecycle"])
        self.assertEqual(1, child.call_count)
        self.assertEqual(["failed"] + ["blocked"] * 5, [item["status"] for item in result["results"]])

    def test_workspace_assignment_failure_blocks_reopen(self):
        responses = [{"status": "passed", "tests": 1}] * 3 + [{"status": "failed", "tests": 1}]
        with patch("phoenix_test_terminal.runner.invoke", side_effect=responses) as child, contextlib.redirect_stdout(io.StringIO()):
            result = run(REPO, ["workspace-lifecycle"])
        self.assertEqual(4, child.call_count)
        self.assertEqual(["blocked", "blocked"], [item["status"] for item in result["results"][-2:]])
        self.assertFalse(result["release_ready"])

    def test_graph_setup_failure_blocks_failure_probes(self):
        responses = [{"status": "passed", "tests": 1}, {"status": "failed", "tests": 1}]
        with patch("phoenix_test_terminal.runner.invoke", side_effect=responses) as child, contextlib.redirect_stdout(io.StringIO()):
            result = run(REPO, ["graph-save"])
        self.assertEqual(2, child.call_count)
        self.assertEqual("blocked", result["results"][-1]["status"])
        self.assertFalse(result["release_ready"])

    def test_graph_failure_is_not_a_green_suite(self):
        responses = [{"status": "passed", "tests": 1}] * 2 + [{"status": "failed", "tests": 1}]
        with patch("phoenix_test_terminal.runner.invoke", side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
            result = run(REPO, ["graph-save"])
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["release_ready"])

    def test_registry_negative_scenarios_both_run_and_cannot_pass_gate(self):
        responses = [{"status": "passed", "tests": 1}] * 4 + [{"status": "failed", "tests": 1}] * 2
        with patch("phoenix_test_terminal.runner.invoke", side_effect=responses) as child, contextlib.redirect_stdout(io.StringIO()):
            result = run(REPO, ["registry-lifecycle"])
        self.assertEqual(6, child.call_count)
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["release_ready"])

    def test_gate_cannot_certify_partial_suite(self):
        fake = {"results": [], "status": "passed", "release_ready": False, "inventory": {"release_gaps": ["Incomplete"]}}
        with patch("phoenix_test_terminal.__main__.run", return_value=fake), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(2, main(["gate"]))

    def test_report_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "existing.json"
            report.write_text("keep")
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                main(["run", "vault", "--report", str(report)])
            self.assertEqual("keep", report.read_text())

    def test_invalid_or_empty_worker_pass_fails_closed(self):
        for data in ("[]", "garbage", '{"status":"passed","tests":0}', '{"status":"passed","tests":1,"skipped":["missing"]}'):
            process = subprocess.CompletedProcess([], 0, data, "")
            with patch("phoenix_test_terminal.runner.subprocess.run", return_value=process):
                self.assertEqual("failed", invoke(REPO, REPO, [], 1)["status"])

    def test_nonzero_exit_overrides_pass(self):
        process = subprocess.CompletedProcess([], 1, '{"status":"passed","tests":1}', "")
        with patch("phoenix_test_terminal.runner.subprocess.run", return_value=process):
            self.assertEqual("failed", invoke(REPO, REPO, [], 1)["status"])

    def test_timeout_is_failure(self):
        with patch("phoenix_test_terminal.runner.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 1)):
            result = invoke(REPO, REPO, [], 1)
        self.assertEqual("failed", result["status"])
        self.assertIn("deadline", result["errors"][0]["detail"])

    def test_worker_preserves_application_exit_diagnostics(self):
        from phoenix_test_terminal import worker

        def preflight_exit(*args):
            print("[PHOENIX][PREFLIGHT] missing libxcb-cursor.so.0", file=sys.stderr)
            raise SystemExit(exit_code)

        for exit_code in (78, 0):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temporary:
                sandbox = Path(temporary).resolve()
                (sandbox / ".phoenix-test-only").touch()
                output = io.StringIO()
                with patch.object(sys, "argv", ["worker", "--root", str(REPO), "--sandbox", str(sandbox), "--cockpit-stage", "create"]), \
                     patch.object(sys, "path", list(sys.path)), \
                     patch.object(sys, "dont_write_bytecode", True), \
                     patch("pathlib.Path.cwd", return_value=sandbox), \
                     patch("phoenix_test_terminal.safety.install_guards"), \
                     patch("phoenix_test_terminal.cockpit_scenario.run", side_effect=preflight_exit), \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(1, worker.main())
                result = json.loads(output.getvalue())
                self.assertEqual("failed", result["status"])
                self.assertIn("missing libxcb-cursor.so.0", result["log"])
                self.assertIn(f"SystemExit: {exit_code}", result["errors"][0]["detail"])

    def test_actual_hanging_worker_is_terminated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "phoenix_test_terminal").mkdir()
            (root / "phoenix_test_terminal/worker.py").write_text("import time\ntime.sleep(30)\n")
            result = invoke(root, root, [], .2)
        self.assertEqual("failed", result["status"])
        self.assertLess(result["elapsed_sec"], 10)

    def test_missing_dependency_worker_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "phoenix_test_terminal").mkdir()
            (root / "phoenix_test_terminal/worker.py").write_text("import nonexistent_phoenix_lab_dependency\n")
            result = invoke(root, root, [], 10)
        self.assertEqual("failed", result["status"])
        self.assertIn("ModuleNotFoundError", result["log"])

    def test_real_audit_guards(self):
        script = r'''
import os, socket, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from phoenix_test_terminal.safety import install_guards
root = Path.cwd()
install_guards(root)
(root / 'allowed').write_text('synthetic')
blocked = 0
for action in [lambda: (root.parent / 'forbidden').write_text('no'),
               lambda: socket.create_connection(('192.0.2.1', 22), timeout=.1),
               lambda: subprocess.run([sys.executable, '-c', 'pass']),
               lambda: os.system('echo no')]:
    try:
        action()
    except PermissionError:
        blocked += 1
assert blocked == 4, blocked
'''
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(REPO)], cwd=temporary, capture_output=True, text=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
