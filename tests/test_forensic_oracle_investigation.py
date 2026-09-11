"""Tests for bounded Oracle forensic evidence and alert results."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))

from agents.python_core.forensic_detective.oracle_investigation import (  # noqa: E402
    MAX_EVIDENCE_CHARS,
    build_oracle_messages,
    parse_oracle_analysis,
    render_oracle_alert,
)


class ForensicOracleInvestigationTests(unittest.TestCase):
    def test_evidence_is_redacted_bounded_and_marked_untrusted(self):
        messages = build_oracle_messages(
            "incident-1",
            {
                "service_name": "site_sentinel",
                "severity": "CRITICAL",
                "api_key": "should-never-leave",
                "details": "authorization: Bearer secret-token",
            },
            [{"details": "event"}] * 50,
            "password=bad-idea",
            max_context_events=4,
        )
        prompt = messages[1]["content"]
        self.assertNotIn("should-never-leave", prompt)
        self.assertNotIn("secret-token", prompt)
        self.assertNotIn("bad-idea", prompt)
        self.assertIn("[REDACTED]", prompt)
        self.assertEqual(4, len(json.loads(
            prompt.split("<EVIDENCE>\n", 1)[1].split("\n</EVIDENCE>", 1)[0]
        )["correlated_events"]))
        self.assertIn("untrusted evidence", messages[0]["content"])

    def test_analysis_is_normalized_and_alert_stays_short(self):
        analysis = parse_oracle_analysis(json.dumps({
            "summary": "Public and origin checks failed.",
            "hypothesis": "The web service may be unavailable.",
            "confidence": 1.4,
            "evidence": ["HTTP probes failed", "origin failed", "extra", "drop"],
            "next_checks": ["Check service", "Inspect proxy", "Review logs", "drop"],
        }))
        self.assertEqual(1.0, analysis["confidence"])
        self.assertEqual(3, len(analysis["evidence"]))
        self.assertEqual(3, len(analysis["next_checks"]))
        alert = render_oracle_alert(analysis)
        self.assertIn("Confidence: 100%", alert)
        self.assertIn("Verify:", alert)
        self.assertIn("Scope: supplied forensic evidence only", alert)

    def test_oversized_evidence_remains_valid_json(self):
        messages = build_oracle_messages(
            "incident-large",
            {f"field-{index}": "x" * 2000 for index in range(40)},
            [],
            "y" * 2000,
        )
        evidence_text = messages[1]["content"].split(
            "<EVIDENCE>\n", 1
        )[1].split("\n</EVIDENCE>", 1)[0]
        evidence = json.loads(evidence_text)
        self.assertTrue(evidence["evidence_truncated"])
        self.assertLessEqual(len(evidence_text), MAX_EVIDENCE_CHARS)

    def test_non_json_and_incomplete_results_fail_closed(self):
        with self.assertRaises(ValueError):
            parse_oracle_analysis("probably nginx")
        with self.assertRaises(ValueError):
            parse_oracle_analysis('{"summary":"missing hypothesis"}')


if __name__ == "__main__":
    unittest.main()
