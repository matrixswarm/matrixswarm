"""Site Sentinel parsing and classification tests."""

from __future__ import annotations

import ast
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "matrixos/agents/python_core/site_sentinel/analysis.py"
AGENT_PATH = ROOT / "matrixos/agents/python_core/site_sentinel/site_sentinel.py"
META_PATH = ROOT / "phoenix/agents_meta/site_sentinel.json"
EDITOR_PATH = ROOT / "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/site_sentinel.py"
INVESTIGATOR_PATH = ROOT / (
    "matrixos/agents/python_core/forensic_detective/factory/watchdog/"
    "site_sentinel/investigator/__init__.py"
)

spec = importlib.util.spec_from_file_location("site_sentinel_analysis", ANALYSIS_PATH)
analysis = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(analysis)


class SiteSentinelTests(unittest.TestCase):
    def test_combined_access_log_parser(self):
        event = analysis.parse_access_line(
            '203.0.113.8 - - [09/Sep/2026:21:00:00 +0000] '
            '"GET /products/1 HTTP/1.1" 404 123 "-" "Scrapy/2.11"'
        )
        self.assertEqual(event["ip"], "203.0.113.8")
        self.assertEqual(event["path"], "/products/1")
        self.assertEqual(event["status"], 404)

    def test_json_log_prefers_cloudflare_client_ip(self):
        event = analysis.parse_access_line(json.dumps({
            "remote_addr": "198.51.100.4",
            "cf_connecting_ip": "203.0.113.9",
            "request_uri": "/",
            "status": 200,
        }))
        self.assertEqual(event["ip"], "203.0.113.9")

    def test_one_edge_failure_is_degraded_not_down(self):
        public = {"ok": False, "transport_ok": False}
        origin = {"ok": True, "transport_ok": True}
        self.assertEqual(
            analysis.classify_target(public, origin),
            ("WARNING", "EDGE_DEGRADED"),
        )

    def test_public_content_mismatch_is_critical(self):
        public = {
            "ok": False,
            "transport_ok": True,
            "content_ok": False,
            "assets_ok": True,
        }
        self.assertEqual(
            analysis.classify_target(public),
            ("CRITICAL", "PUBLIC_CONTENT_MISMATCH"),
        )

    def test_aggressive_ip_is_identified(self):
        events = [
            {
                "ip": "203.0.113.10",
                "path": f"/catalog/{index}",
                "status": 404,
                "user_agent": "Scrapy/2.11",
            }
            for index in range(310)
        ]
        result = analysis.summarize_traffic(
            events,
            window_sec=60,
            top_n=5,
            per_ip_warning_rpm=120,
            per_ip_critical_rpm=300,
        )
        self.assertEqual(result["severity"], "CRITICAL")
        self.assertEqual(result["top_ips"][0]["ip"], "203.0.113.10")
        self.assertTrue(result["top_ips"][0]["aggressive"])

    def test_metadata_and_editor_contract(self):
        metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
        self.assertEqual(metadata["name"], "site_sentinel")
        self.assertEqual(metadata["config"]["report_to_role"], "hive.forensics.data_feed")
        compile(EDITOR_PATH.read_text(encoding="utf-8"), str(EDITOR_PATH), "exec")
        compile(AGENT_PATH.read_text(encoding="utf-8"), str(AGENT_PATH), "exec")
        compile(
            INVESTIGATOR_PATH.read_text(encoding="utf-8"),
            str(INVESTIGATOR_PATH),
            "exec",
        )
        self.assertIn('"service_name": "site_sentinel"', AGENT_PATH.read_text(encoding="utf-8"))

    def test_agent_uses_package_import_for_pod_execution(self):
        tree = ast.parse(AGENT_PATH.read_text(encoding="utf-8"))
        imported_modules = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        self.assertIn("site_sentinel.analysis", imported_modules)
        self.assertNotIn("analysis", imported_modules)


if __name__ == "__main__":
    unittest.main()
