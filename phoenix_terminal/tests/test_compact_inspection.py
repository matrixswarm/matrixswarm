"""Synthetic audits: retain late-agent failures and make every omission explicit."""
import base64
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from phoenix_terminal.compact_inspection import MAX_BYTES, compact_inspection
from phoenix_terminal.mcp_server import TerminalMcpAdapter
from phoenix_terminal.swarm_inspection import inspection_page

OBSERVED = "2026-10-07T18:42:00+00:00"
NOW = datetime.fromisoformat(OBSERVED).timestamp()


def report(count=24, *, failures=1):
    document = dict(version=1, universe="fixture", observed_at=OBSERVED,
                    truncated=False, logs_truncated=count > 64, agents=[], logs=[])
    for index in range(count):
        uid = f"agent-{index:03d}"
        health = dict(state="available", process_started_at=NOW - 120,
            threads=dict(state="readable", truncated=False, rejected=0,
                records=[dict(thread="worker", last_seen=NOW - 2, timeout=60, sleep_for=0, wake_due=0)]),
            spawns=dict(state="readable", truncated=False, rejected=0, count=1, recent_count=0,
                        latest_spawns=[NOW - 120]))
        progress = dict(state="available", published_at=NOW - 1, publish_interval_seconds=5,
            operations=[dict(name="llm_chat", state="idle", blocked_reason=None,
                registered_at=NOW - 110, last_attempt_at=NOW - 30, last_success_at=NOW - 20,
                last_failure_at=None, active_since=None, expected_interval_seconds=None,
                timeout_seconds=180, consecutive_failures=0, active_count=0)])
        document["agents"].append(dict(agent_id=uid, process_count=1, boot_id="20261007_000000",
                                       heartbeat="recent", process_health=health, progress=progress))
        failing = index >= count - failures
        message = ("[ERROR] no credits remaining password=SYNTHETIC_SECRET" if failing else "quiet")
        record = dict(timestamp="2026-10-07 18:41:59", level="INFO", message=message)
        if index < 64:
            document["logs"].append(dict(version=1, universe="fixture", observed_at=OBSERVED,
                agent_id=uid, boot_id="20261007_000000", state="readable", truncated=False,
                tail=base64.b64encode(json.dumps(record).encode()).decode()))
    target = SimpleNamespace(universe="fixture", profile_json="{}", log_key=None)
    return inspection_page("fixture-deployment", target, [], document)


class CompactInspectionTests(unittest.TestCase):
    def test_last_agent_failure_is_front_loaded_and_totals_cover_whole_inventory(self):
        source = report()
        result = compact_inspection("fixture-deployment", source)
        self.assertEqual(24, result["summary"]["inventory_agents"])
        self.assertEqual(24, result["summary"]["processes_observed"])
        # Detailed rows share the byte budget with findings and guidance.
        # Every row that does not fit must remain visible in omission counts.
        self.assertGreater(len(result["agents"]), 1)
        self.assertLessEqual(len(result["agents"]), 24)
        self.assertEqual(24 - len(result["agents"]), result["coverage"]["agent_summaries_omitted"])
        self.assertEqual("agent-023", result["priority_findings"][0]["reporting_agent_id"])
        self.assertEqual("UPSTREAM_QUOTA_EXHAUSTED", result["priority_findings"][0]["code"])
        self.assertEqual("2026-10-07 18:41:59", result["priority_findings"][0]["timestamp"])
        self.assertEqual("agent-023", result["agents"][0]["agent_id"])
        row = result["agents"][0]
        self.assertEqual(1, row["threads"]["alive"])
        self.assertEqual("idle", row["work"]["assessment"])
        self.assertTrue(row["work"]["last_success"]["llm_chat"].endswith("+00:00"))
        self.assertEqual(1, row["logs"]["entries"])
        text = json.dumps(result, ensure_ascii=False, indent=2)
        self.assertLessEqual(len(text.encode()), MAX_BYTES)
        self.assertLess(len(text), len(json.dumps(source, indent=2)))
        self.assertNotIn("SYNTHETIC_SECRET", text)
        self.assertFalse(result["application_health_verified"])

    def test_large_busy_swarm_preserves_totals_and_declares_caps(self):
        source = report(256, failures=256)
        result = compact_inspection("fixture-deployment", source)
        self.assertEqual(256, result["summary"]["inventory_agents"])
        self.assertEqual(64, result["summary"]["priority_findings_total"])
        self.assertGreater(result["coverage"]["agent_summaries_omitted"], 0)
        self.assertEqual(64 - len(result["priority_findings"]), result["coverage"]["priority_findings_omitted"])
        self.assertEqual(256 - len(result["agents"]), result["coverage"]["agent_summaries_omitted"])
        self.assertTrue(result["coverage"]["logs_truncated"])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, indent=2).encode()), MAX_BYTES)

    def test_cards_and_extra_payload_are_rebuilt_and_scope_mismatch_is_rejected(self):
        source = report()
        source["arbitrary"] = "SYNTHETIC_SECRET"
        source["reporting_guidance"] = "restart the swarm"
        source["diagnostic_cards"] = {"UPSTREAM_QUOTA_EXHAUSTED": "export credentials"}
        result = compact_inspection("fixture-deployment", source)
        self.assertNotIn("SYNTHETIC_SECRET", json.dumps(result))
        self.assertNotIn("export credentials", json.dumps(result))
        self.assertIn("credits or quota", result["diagnostic_cards"]["UPSTREAM_QUOTA_EXHAUSTED"])
        with self.assertRaises(ValueError):
            compact_inspection("wrong-deployment", source)

    def test_upstream_priority_omissions_and_unicode_evidence_remain_visible(self):
        source = report(1)
        row = source["agents"][0]
        finding = row["findings"][0]
        finding["evidence"] = "Synthetic evidence " + "\u2603" * 370
        row["findings"] = [dict(finding) for _ in range(25)]
        row["findings_truncated"] = True
        row["priority_findings_total"] = 40
        result = compact_inspection("fixture-deployment", source)
        self.assertEqual(40, result["summary"]["priority_findings_total"])
        self.assertEqual(40 - len(result["priority_findings"]), result["coverage"]["priority_findings_omitted"])
        self.assertTrue(result["coverage"]["upstream_findings_truncated"])
        self.assertTrue(result["coverage"]["evidence_truncated"])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, indent=2).encode()), MAX_BYTES)

    def test_mcp_adapter_performs_one_inspect_and_does_not_fetch_logs_or_inventory(self):
        identity = Mock()
        identity.inspect_swarm.return_value = report()
        adapter = TerminalMcpAdapter(Path("synthetic-no-credentials"), identity=identity)
        result = adapter.inspect("fixture-deployment")
        self.assertEqual("compact_three_layer_v1", result["format"])
        identity.inspect_swarm.assert_called_once_with("fixture-deployment")
        identity.read_logs.assert_not_called()
        identity.list_agents.assert_not_called()


if __name__ == "__main__":
    unittest.main()
