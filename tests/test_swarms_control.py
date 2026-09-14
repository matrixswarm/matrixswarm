"""Remote Swarms inventory and stop-command security regressions."""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))

from matrix_gui.modules.swarms import remote  # noqa: E402


def snapshot(*universes):
    return json.dumps(
        {
            "version": 1,
            "universes": [
                {
                    "universe": name,
                    "status": "active",
                    "agent_count": count,
                    "rss_bytes": 1024,
                    "cpu_percent": 1.5,
                    "agents": [],
                }
                for name, count in universes
            ],
        }
    )


class Stream:
    def __init__(self, payload=b"", status=0):
        self.payload = payload
        self.channel = Mock()
        self.channel.recv_exit_status.return_value = status

    def read(self, _limit):
        return self.payload


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []
        self.closed = False

    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        output, error, status = self.responses.pop(0)
        return Mock(), Stream(output, status), Stream(error, status)

    def close(self):
        self.closed = True


class SwarmsRemoteTests(unittest.TestCase):
    def test_public_inventory_is_bounded_and_normalized(self):
        parsed = remote.parse_snapshot(snapshot(("phoenix", 9), ("backup_service", 7)))
        self.assertEqual(
            [item["universe"] for item in parsed],
            ["backup_service", "phoenix"],
        )
        self.assertNotIn("agents", parsed[0])
        malicious = json.loads(snapshot(("phoenix", 9)))
        malicious["universes"][0]["universe"] = "phoenix; shutdown -h now"
        with self.assertRaisesRegex(ValueError, "universe"):
            remote.parse_snapshot(json.dumps(malicious))

    def test_kill_command_is_exact_stop_only(self):
        command = remote.build_kill_command("backup_service")
        self.assertIn("matrixd kill --universe backup_service", command)
        self.assertNotIn("--clean", command)
        self.assertNotIn("--delete", command)
        self.assertNotIn("matrixd *", command)
        for invalid in ("", "../phoenix", "phoenix;id", "a" * 33):
            with self.assertRaises(ValueError):
                remote.build_kill_command(invalid)

    def test_kill_all_lists_and_stops_over_one_pinned_connection(self):
        before = snapshot(("backup_service", 7), ("phoenix", 9)).encode()
        after = snapshot().encode()
        client = Client(
            [
                (before, b"", 0),
                (b"stopped backup", b"", 0),
                (b"stopped phoenix", b"", 0),
                (after, b"", 0),
            ]
        )
        with patch.object(
            remote,
            "connect_ssh_profile",
            return_value=(client, "SHA256:fixture"),
        ) as connect:
            result = remote.perform({"host": "fixture"}, "kill_all")

        connect.assert_called_once()
        self.assertTrue(client.closed)
        self.assertEqual(result["stopped"], ["backup_service", "phoenix"])
        self.assertEqual(result["universes"], [])
        self.assertEqual(len(client.commands), 4)
        self.assertEqual(client.commands[0][0], remote.LIST_COMMAND)
        self.assertIn("--universe backup_service", client.commands[1][0])
        self.assertIn("--universe phoenix", client.commands[2][0])
        self.assertEqual(client.commands[3][0], remote.LIST_COMMAND)

    def test_top_level_ui_contract_has_no_polling_inventory_timer(self):
        dialog = (
            ROOT / "phoenix/matrix_gui/modules/swarms/swarms_dialog.py"
        ).read_text(encoding="utf-8")
        controls = (
            ROOT / "phoenix/matrix_gui/core/phoenix_control_panel.py"
        ).read_text(encoding="utf-8")
        self.assertIn('QPushButton("🌌 Swarms")', controls)
        self.assertIn('QPushButton("⛔ Kill All on This Server")', dialog)
        self.assertIn('QPushButton("⛔ Kill")', dialog)
        self.assertIn("setSingleShot(True)", dialog)
        self.assertNotIn("setInterval(3000)", dialog)
        self.assertIn("Type KILL ALL to continue", dialog)


if __name__ == "__main__":
    unittest.main()
