"""Offline Qt and agent-contract tests for the Matrix SSH perimeter panel."""

import importlib
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
except ImportError:
    QApplication = None


class Bus:
    def __init__(self):
        self.listeners = {}
        self.sent = []

    def on(self, name, handler):
        self.listeners.setdefault(name, []).append(handler)

    def off(self, name, handler):
        self.listeners[name].remove(handler)

    def emit(self, name, **kwargs):
        self.sent.append((name, {**kwargs, "packet": kwargs["packet"].get_packet()}))


@unittest.skipIf(QApplication is None, "Phoenix GUI dependencies not installed")
class MatrixSSHPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module(
            "matrix_gui.core.panel.custom_panels.matrix_ssh.matrix_ssh"
        )
        cls.app = QApplication.instance() or QApplication([])
        if os.name == "nt":
            from PyQt6.QtGui import QFont, QFontDatabase
            font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/consola.ttf"
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
                cls.app.setFont(QFont("Consolas", 10))

    def setUp(self):
        self.bus = Bus()
        self.panel = self.module.MatrixSsh("session-a", self.bus)
        self.panel.resize(1000, 600)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def request(self):
        name, envelope = self.bus.sent[-1]
        self.assertEqual("outbound.message", name)
        self.assertEqual("outgoing.command", envelope["channel"])
        self.assertEqual("session-a", envelope["session_id"])
        self.assertEqual("cmd_service_request", envelope["packet"]["handler"])
        return envelope["packet"]["content"]

    def test_metadata_resolves_through_standard_panel_loader(self):
        meta = json.loads((ROOT / "phoenix/agents_meta/matrix_ssh.json").read_text(encoding="utf-8"))
        panel_name, = meta["config"]["ui"]["panel"]
        mod_path, leaf = panel_name.rsplit(".", 1)
        module = importlib.import_module(f"matrix_gui.core.panel.custom_panels.{mod_path}.{leaf}")
        self.assertIs(self.module.MatrixSsh, getattr(module, "".join(p.capitalize() for p in leaf.split("_"))))
        roles = meta["config"]["service-manager"][0]["role"]
        for service in ("matrix_ssh.toggle_perimeter", "hive.toggle_perimeter", "matrix_ssh.status"):
            self.assertTrue(any(role.startswith(service + "@") for role in roles))

    def test_open_and_timed_lockdown_packets(self):
        self.assertEqual([], self.bus.sent)  # Showing a panel changes no remote state.
        self.panel.send_btn.click()
        request = self.request()
        self.assertEqual("matrix_ssh.toggle_perimeter", request["service"])
        self.assertEqual({
            "lockdown_state": 0, "lockdown_time": 0, "session_id": "session-a",
            "return_handler": "matrix_ssh_panel.perimeter_ack",
        }, request["payload"])
        self.panel.state_combo.setCurrentText("lockdown")
        self.panel.time_input.setText(" 300 ")
        self.panel.send_btn.click()
        self.assertEqual(1, self.request()["payload"]["lockdown_state"])
        self.assertEqual(300, self.request()["payload"]["lockdown_time"])
        self.assertIn("awaiting agent acknowledgment", self.panel.output_box.toPlainText())

    def test_hive_scope_and_refresh_status_are_distinct(self):
        self.panel.target_combo.setCurrentIndex(1)
        self.panel.send_btn.click()
        self.assertEqual("hive.toggle_perimeter", self.request()["service"])
        self.panel.refresh_btn.click()
        self.assertEqual({
            "service": "matrix_ssh.status",
            "payload": {"session_id": "session-a", "return_handler": "matrix_ssh_panel.status_ack"},
        }, self.request())

    def test_invalid_duration_never_sends(self):
        self.panel.state_combo.setCurrentText("lockdown")
        for text in ("-1", "abc", "1.5"):
            with self.subTest(text=text):
                self.panel.time_input.setText(text)
                self.panel.send_btn.click()
                self.assertEqual([], self.bus.sent)
                self.assertIn("Invalid lockdown time", self.panel.output_box.toPlainText())

    def test_indefinite_lockdown_requires_explicit_yes(self):
        self.panel.state_combo.setCurrentText("lockdown")
        for response in (QMessageBox.StandardButton.No, QMessageBox.StandardButton.Cancel,
                         QMessageBox.StandardButton.Close):
            with self.subTest(response=response), mock.patch.object(
                self.module.QMessageBox, "warning", return_value=response
            ) as warning:
                self.panel.send_btn.click()
                self.assertEqual([], self.bus.sent)
                self.assertEqual(QMessageBox.StandardButton.No, warning.call_args.args[-1])
        with mock.patch.object(self.module.QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            self.panel.send_btn.click()
        self.assertEqual(1, self.request()["payload"]["lockdown_state"])
        self.assertEqual(0, self.request()["payload"]["lockdown_time"])

    def test_verified_callbacks_are_session_scoped_and_gui_queued(self):
        self.panel._status_ack("other-session", payload={"lockdown_state": "Wrong"})
        self.app.processEvents()
        self.assertEqual("", self.panel.output_box.toPlainText())
        worker = threading.Thread(target=self.panel._status_ack, kwargs={
            "session_id": "session-a", "payload": {"lockdown_state": "Open", "poll_interval": 1},
        })
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.app.processEvents()
        self.assertIn('"lockdown_state": "Open"', self.panel.output_box.toPlainText())
        self.panel._perimeter_ack("session-a", payload={"lockdown_state": "Lockdown"})
        self.app.processEvents()
        self.assertIn("SSH Perimeter Toggle ACK", self.panel.output_box.toPlainText())

    def test_lifecycle_unsubscribes_without_duplicate_listeners(self):
        self.panel._connect_signals()
        self.assertEqual(2, len(self.bus.listeners))
        self.assertTrue(all(len(handlers) == 1 for handlers in self.bus.listeners.values()))
        self.assertTrue(all(name.startswith("inbound.verified.matrix_ssh_panel.") for name in self.bus.listeners))
        self.panel.hide()
        self.app.processEvents()
        self.assertTrue(all(not handlers for handlers in self.bus.listeners.values()))
        self.panel.show()
        self.app.processEvents()
        self.assertTrue(all(len(handlers) == 1 for handlers in self.bus.listeners.values()))

    def test_toolbar_opens_specialty_panel_and_optional_screenshot(self):
        self.panel.session_window = mock.Mock()
        button, = self.panel.get_panel_buttons()
        self.assertEqual("Matrix SSH", button.text)
        button.handler()
        self.panel.session_window.show_specialty_panel.assert_called_once_with(self.panel)
        if os.environ.get("MATRIX_SSH_PANEL_SCREENSHOT"):
            self.assertTrue(self.panel.grab().save(os.environ["MATRIX_SSH_PANEL_SCREENSHOT"]))

    def test_panel_packet_drives_existing_agent_and_timed_reopening(self):
        from tests.test_matrix_ssh_transport import AGENT, load_class, load_functions
        parse_bool = load_functions(AGENT, {"_parse_bool"})["_parse_bool"]
        clock = mock.Mock(return_value=1000)
        agent_class = load_class(AGENT, "Agent", {
            "BootAgent": object, "IdentityObject": object, "_parse_bool": parse_bool,
            "time": SimpleNamespace(time=clock), "interruptible_sleep": mock.Mock(),
        })
        agent = agent_class.__new__(agent_class)
        agent.tree_node = {"config": {}}
        agent.crypto_reply = mock.Mock()
        agent.log = mock.Mock()
        agent._emit_beacon = mock.Mock()
        agent._process_inbox = mock.Mock()
        agent.poll_interval = 1
        agent.inbox = Path("test-inbox")
        self.panel.state_combo.setCurrentText("lockdown")
        self.panel.time_input.setText("60")
        self.panel.send_btn.click()
        agent.cmd_toggle_perimeter(self.request()["payload"], None)
        self.assertTrue(agent.lockdown_state)
        self.assertEqual(1060, agent.lockdown_expires)
        ack = agent.crypto_reply.call_args.kwargs
        self.assertEqual("matrix_ssh_panel.perimeter_ack", ack["response_handler"])
        self.assertEqual("session-a", ack["session_id"])
        self.panel._perimeter_ack("session-a", payload=ack["payload"])
        self.app.processEvents()
        self.assertIn("Lockdown", self.panel.output_box.toPlainText())
        agent.worker()
        agent._process_inbox.assert_not_called()
        clock.return_value = 1060
        agent.worker()
        self.assertFalse(agent.lockdown_state)
        agent._process_inbox.assert_called_once()
        self.panel.refresh_btn.click()
        agent.cmd_status(self.request()["payload"], None)
        self.assertEqual("matrix_ssh_panel.status_ack", agent.crypto_reply.call_args.kwargs["response_handler"])
        self.assertEqual("Open", agent.crypto_reply.call_args.kwargs["payload"]["lockdown_state"])


if __name__ == "__main__":
    unittest.main()
