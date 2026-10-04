"""Real offscreen Qt clients linked through actual agent handlers and storage."""
import base64
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QMessageBox
from matrix_gui.core.panel.custom_panels.drop_vault.drop_vault import DropVault, _expire_clipboard
from matrix_gui.core.panel.custom_panels.drop_vault.local_files import FileJob, MAX_BYTES
from test_drop_vault_store import Persistence, DropStore, load_agent_class, IdentityObject, CHUNK_BYTES, upload


class Bus:
    def __init__(self):
        self.listeners, self.queue = {}, []

    def on(self, name, callback):
        self.listeners.setdefault(name, []).append(callback)

    def off(self, name, callback):
        self.listeners[name].remove(callback)

    def emit(self, name, **kwargs):
        self.queue.append(deepcopy(kwargs["packet"].get_packet()["content"]["payload"]))


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.name == "nt":
            from PyQt6.QtGui import QFont, QFontDatabase
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/consola.ttf"))
            cls.app.setFont(QFont("Consolas", 10))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.persistence = Persistence(self.temp.name)
        self.store = DropStore(self.persistence)
        self.addCleanup(self.store.close)
        cls = load_agent_class()
        self.agent = cls.__new__(cls)
        self.agent.command_line_args = {"universal_id": "drop-a"}
        self.agent.get_matrix_universal_id = lambda: "matrix"
        self.agent._rpc_role = "hive.rpc"
        self.agent.store = self.store
        self.agent.log = lambda *a, **k: None
        self.replies = []
        self.agent.crypto_reply = lambda **kwargs: self.replies.append(kwargs)
        self.panels = []
        self.panel = self.make_panel("session-one")

    def make_panel(self, session):
        bus = Bus()
        panel = DropVault(session, bus, node={"universal_id": "drop-a"})
        panel.resize(1150, 780)
        self.panels.append(panel)
        panel.show()
        self.app.processEvents()
        return panel

    def tearDown(self):
        for panel in self.panels:
            panel.close()
            panel.deleteLater()
        QApplication.clipboard().clear()
        self.app.processEvents()

    def pump(self, panel=None):
        panel = panel or self.panel
        count = 0
        while panel.bus.queue:
            count += 1
            self.assertLess(count, 2000, "protocol did not settle")
            request = panel.bus.queue.pop(0)
            self.agent.cmd_request(request, None, IdentityObject(True, "matrix"))
            for result in self.replies:
                panel._callback(result["session_id"], payload={"content": result["payload"]})
            self.replies.clear()
            self.app.processEvents()

    def select_first(self, panel=None):
        panel = panel or self.panel
        panel.listing.setCurrentItem(panel.listing.topLevelItem(0))
        self.pump(panel)

    def test_two_clients_paste_poll_retrieve_copy_and_delete(self):
        self.pump()
        self.panel.title.setText("Synthetic travel note")
        self.panel.notes.setPlainText("TEST-ONLY")
        self.panel.paste.setPlainText("SYNTHETIC PRIVATE TEXT\nline two")
        self.panel.send_text.click()
        self.pump()
        self.assertEqual(self.store.listing()["total_items"], 1)
        self.assertEqual(self.panel.paste.toPlainText(), "")
        other = self.make_panel("session-two")
        self.pump(other)
        self.select_first(other)
        self.assertEqual(other.preview.toPlainText(), "SYNTHETIC PRIVATE TEXT\nline two")
        self.assertIn("TEST-ONLY", other.detail.text())
        other.copy.click()
        self.assertEqual(QApplication.clipboard().text(), other.preview.toPlainText())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            other.delete.click()
        self.pump(other)
        self.assertEqual(self.store.listing()["total_items"], 0)
        self.panel.check.click()
        self.pump()
        self.assertEqual(self.panel.listing.topLevelItemCount(), 0)

    def test_paste_confirmation_and_failure_survive_inbox_refresh(self):
        self.pump()
        self.panel.paste.setPlainText("SYNTHETIC PASTE")
        self.panel.send_text.click()
        self.assertIn("waiting for upload", self.panel.paste_feedback.text())
        self.pump()
        self.assertIn("saved encrypted", self.panel.paste_feedback.text())
        self.panel.check.click()
        self.pump()
        self.assertIn("saved encrypted", self.panel.paste_feedback.text())

        self.panel.paste.setPlainText("SECOND SYNTHETIC PASTE")
        self.panel.send_text.click()
        pending = dict(self.panel.pending)
        self.panel.bus.queue.clear()
        self.panel._callback(self.panel.session_id, payload={"content": {
            "token": self.panel.token, "agent_uid": self.panel.agent_uid,
            "request_id": pending["id"], "operation": "begin",
            "ok": False, "error": "Inbox quota reached"}})
        self.app.processEvents()
        self.assertIn("Inbox quota reached", self.panel.paste_feedback.text())
        self.panel.check.click()
        self.pump()
        self.assertIn("Inbox quota reached", self.panel.paste_feedback.text())
        self.assertEqual(self.panel.paste.toPlainText(), "SECOND SYNTHETIC PASTE")

    def test_paste_ack_timeout_keeps_stage_and_draft_visible(self):
        self.pump()
        self.panel.paste.setPlainText("SYNTHETIC ACK TIMEOUT")
        self.panel.send_text.click()
        self.assertEqual(self.panel.pending["operation"], "begin")
        self.panel.bus.queue.clear()  # Simulate missing relay acknowledgement.
        self.panel.pending["started"] = time.monotonic() - 31
        self.panel._tick()
        self.assertIn("begin", self.panel.paste_feedback.text())
        self.assertIn("retrying once", self.panel.paste_feedback.text())
        self.panel.bus.queue.clear()
        self.panel.pending["started"] = time.monotonic() - 31
        self.panel._tick()
        self.assertIn("No acknowledgement", self.panel.paste_feedback.text())
        self.panel.check.click()
        self.pump()
        self.assertIn("No acknowledgement", self.panel.paste_feedback.text())
        self.assertEqual(self.panel.paste.toPlainText(), "SYNTHETIC ACK TIMEOUT")

    def test_binary_chunks_retrieve_without_plaintext_cache(self):
        self.pump()
        data = bytes(range(256))*350
        self.panel._upload(data, "file", "synthetic.bin")
        self.pump()
        self.select_first()
        self.assertEqual(self.panel.loaded[1], data)
        self.assertTrue(self.panel.copy_file.isEnabled())
        self.assertIsNone(self.panel.exported)
        self.assertFalse(self.panel.drag.isEnabled())
        for path in Path(self.temp.name).rglob("*"):
            if path.is_file() and path.suffix == ".aes":
                self.assertNotIn(data, path.read_bytes())

    def test_oversize_file_and_paste_are_rejected_before_network_upload(self):
        from test_drop_vault_store import MAX_OBJECT_BYTES
        self.assertEqual(MAX_BYTES, 1024 * 1024)
        self.assertEqual(MAX_BYTES, MAX_OBJECT_BYTES)
        self.pump()
        self.panel.paste.setPlainText("retained draft")
        # UTF-8 byte size, not the number of visible characters.
        self.panel._draft_text("é" * (MAX_BYTES // 2 + 1))
        self.assertEqual(self.panel.paste.toPlainText(), "retained draft")
        self.assertIn("1 MiB", self.panel.status.text())
        self.panel.paste.setPlainText("x" * (MAX_BYTES + 1))
        self.panel.send_text.click()
        self.assertIn("1 MiB", self.panel.status.text())
        self.assertEqual(self.panel.bus.queue, [])
        self.assertIsNone(self.panel.transfer)
        self.panel._upload(b"x" * (MAX_BYTES + 1), "file", "large.bin")
        self.assertEqual(self.panel.bus.queue, [])
        self.assertIsNone(self.panel.transfer)
        source = Path(self.temp.name) / "too-large.bin"
        with source.open("wb") as stream:
            stream.truncate(MAX_BYTES + 1)
        job = FileJob("read", source)
        completed, errors = [], []
        job.completed.connect(completed.append)
        job.failed.connect(errors.append)
        job.run()
        self.assertEqual(completed, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.store.listing()["total_items"], 0)

    def test_production_https_and_ssh_chunk_wrappers_fit_perimeter_guard(self):
        from Crypto.PublicKey import RSA
        from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
        from matrix_gui.core.utils.crypto_utils import sign_data
        from matrix_gui.modules.net.connector.egress.ssh import SSHConnector
        from core.python_core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size
        self.pump()
        key = RSA.generate(2048)
        signing = {"pubkey": key.publickey().export_key().decode(),
                   "remote_privkey": key.export_key().decode()}
        deployment = {"agents": [{"name": "matrix", "universal_id": "matrix-test"}],
                      "certs": {uid: {"signing": signing} for uid in ("matrix-test", "ssh-test")}}
        # Exercise the actual panel packet and dispatcher encryption helper,
        # then the HTTPS signing shape and the actual SSH envelope builder.
        # No socket, deployed credential or remote server is involved.
        cases = {
            "chunk": dict(object_id="a"*32, offset=MAX_BYTES-CHUNK_BYTES,
                          data=base64.b64encode(b"x"*CHUNK_BYTES).decode()),
            "begin": dict(object_id="a"*32, kind="file", title="t"*256,
                          filename="f"*255, notes="n"*4096, size=MAX_BYTES, sha256="a"*64),
        }
        for operation, args in cases.items():
            with self.subTest(operation=operation), patch.object(self.panel.bus, "emit") as emit:
                self.panel._send(operation, args, "r"*128)
                raw = emit.call_args.kwargs["packet"].get_packet()
                secured = wrap_packet_securely(raw, deployment, sign=True, encrypt=True)
                inner = {"matrix_packet": secured.get_packet(), "ts": int(time.time()),
                         "session_id": self.panel.session_id}
                https_body = {"sig": sign_data(inner, key), "content": inner}
                diagnostics = []
                self.assertTrue(guard_packet_size(https_body["content"]["matrix_packet"], diagnostics.append), diagnostics)
                # Bypass connector initialization: _secure_envelope only builds
                # the bytes; send/upload/connect are deliberately never called.
                connector = SSHConnector.__new__(SSHConnector)
                connector.deployment, connector.target_uid = deployment, "ssh-test"
                connector.session_id, connector._recipient = self.panel.session_id, "h"*64
                ssh_body = json.loads(connector._secure_envelope(secured, "t"*32))
                self.assertTrue(guard_packet_size(ssh_body, diagnostics.append), diagnostics)
                self.assertLess(len(json.dumps(https_body).encode()), 32*1024)
                self.assertLess(len(json.dumps(ssh_body).encode()), 32*1024)
        # A logical item must never be inserted as one packet.
        self.assertFalse(guard_packet_size({"handler": "cmd_request", "content": {
            "data": base64.b64encode(b"x"*MAX_BYTES).decode()}}, lambda _: None))

    def test_callbacks_cannot_cross_session_token_agent_or_request(self):
        original = deepcopy(self.panel.pending)
        valid = dict(token=self.panel.token, agent_uid="drop-a", request_id=original["id"],
                     operation="list", ok=True, entries=[], next_before=None)
        self.panel._callback("other", payload={"content": valid})
        for changes in ({"token": "bad"}, {"agent_uid": "other"}, {"request_id": "wrong"}, {"operation": "read"}):
            self.panel._callback(self.panel.session_id, payload={"content": dict(valid, **changes)})
        self.app.processEvents()
        self.assertEqual(self.panel.pending, original)

    def test_polling_preserves_draft_selection_and_stops_hidden(self):
        upload(self.store, b"existing")
        self.pump()
        self.select_first()
        self.panel.paste.setPlainText("unsent draft")
        selected = self.panel._selected()
        self.panel._last_poll = 0
        self.panel._tick()
        self.pump()
        self.assertEqual(self.panel._selected(), selected)
        self.assertEqual(self.panel.preview.toPlainText(), "existing")
        self.assertEqual(self.panel.paste.toPlainText(), "unsent draft")
        self.panel.hide()
        self.app.processEvents()
        self.assertFalse(self.panel.timer.isActive())
        self.assertFalse(self.panel._signals_connected)
        self.assertIsNone(self.panel.loaded)
        self.assertEqual(self.panel.preview.toPlainText(), "")

    def test_selection_and_delete_remain_available_during_background_list(self):
        upload(self.store, b"synthetic drop")
        self.pump()
        self.panel._last_poll = 0
        previous_status = self.panel.status.text()
        self.panel._tick()
        self.assertEqual(self.panel.pending["operation"], "list")
        self.assertEqual(self.panel.status.text(), previous_status)
        self.assertTrue(self.panel.listing.isEnabled())
        self.panel.listing.setCurrentItem(self.panel.listing.topLevelItem(0))
        self.assertEqual(self.panel.pending["operation"], "read")
        self.pump()  # The superseded list reply must not displace the read.
        self.assertEqual(self.panel.preview.toPlainText(), "synthetic drop")
        self.panel._last_poll = 0
        self.panel._tick()
        self.assertEqual(self.panel.pending["operation"], "list")
        self.assertTrue(self.panel.delete.isEnabled())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.panel.delete.click()
        self.assertEqual(self.panel.pending["operation"], "delete")
        self.pump()  # A late list response must not undo the deletion.
        self.assertEqual(self.store.listing()["total_items"], 0)
        self.assertEqual(self.panel.listing.topLevelItemCount(), 0)

    def test_lost_commit_ack_retries_same_id_without_duplicate(self):
        self.pump()
        self.panel._upload(b"", "file", "empty.txt")
        begin_request = self.panel.bus.queue.pop(0)
        self.agent.cmd_request(begin_request, None, IdentityObject(True, "matrix"))
        result = self.replies.pop()
        self.panel._callback(self.panel.session_id, payload={"content": result["payload"]})
        self.app.processEvents()
        commit = self.panel.bus.queue.pop(0)
        self.agent.cmd_request(commit, None, IdentityObject(True, "matrix"))
        self.replies.clear()  # Simulate a dropped callback, not a failed commit.
        original = self.panel.pending["id"]
        self.panel.pending["started"] = 0
        self.panel._tick()
        self.assertEqual(self.panel.bus.queue[-1]["request_id"], original)
        self.pump()
        self.assertEqual(self.store.listing()["total_items"], 1)

    def test_newer_typing_survives_upload_ack(self):
        self.pump()
        self.panel.paste.setPlainText("first version")
        self.panel.send_text.click()
        self.panel.paste.setPlainText("second version")
        self.pump()
        self.assertEqual(self.panel.paste.toPlainText(), "second version")

    def test_paste_editor_accepts_browser_text_only_as_unsent_draft(self):
        self.pump()
        self.assertIs(self.panel.tabs.cornerWidget(Qt.Corner.TopRightCorner),
                      self.panel.paste_clipboard)
        self.assertTrue(self.panel.paste_clipboard.isVisible())
        browser_selection = QMimeData()
        browser_selection.setHtml("<b>Selected text</b>")
        browser_selection.setText("Selected text")
        self.assertTrue(self.panel.paste.canInsertFromMimeData(browser_selection))
        self.panel.paste.insertFromMimeData(browser_selection)
        self.assertEqual(self.panel.paste.toPlainText(), "Selected text")
        self.assertIn("this text has not been sent", self.panel.status.text())
        self.assertEqual(self.panel.bus.queue, [])

        file_drop = QMimeData()
        file_drop.setUrls([QUrl.fromLocalFile(str(Path(self.temp.name) / "local.txt"))])
        file_drop.setText("local file")
        self.assertFalse(self.panel.paste.canInsertFromMimeData(file_drop))
        self.panel.paste.insertFromMimeData(file_drop)
        self.assertEqual(self.panel.paste.toPlainText(), "Selected text")

        too_large = QMimeData()
        too_large.setText("x" * MAX_BYTES)
        self.panel.paste.insertFromMimeData(too_large)
        self.assertEqual(self.panel.paste.toPlainText(), "Selected text")
        self.assertIn("1 MiB", self.panel.status.text())

    def test_browser_drag_into_paste_header_and_editor_viewport(self):
        self.pump()
        mime = QMimeData()
        mime.setText("Dragged from browser")
        for target in (self.panel.tabs.widget(0), self.panel.paste_clipboard,
                       self.panel.paste.viewport()):
            enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(target, enter)
            self.assertTrue(enter.isAccepted())
            drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(target, drop)
            self.assertTrue(drop.isAccepted())
        self.assertEqual(self.panel.paste.toPlainText(), "Dragged from browser" * 3)
        self.assertEqual(self.panel.bus.queue, [])

        html_only = QMimeData()
        html_only.setHtml("<b>HTML only</b>")
        enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, html_only,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.panel.paste_clipboard, enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, html_only,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.panel.paste_clipboard, drop)
        self.assertTrue(drop.isAccepted())
        self.assertIn("HTML only", self.panel.paste.toPlainText())

        local_file = QMimeData()
        local_file.setUrls([QUrl.fromLocalFile(str(Path(self.temp.name) / "local.txt"))])
        local_file.setText("Must not become a paste")
        enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, local_file,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.panel.paste_clipboard, enter)
        self.assertFalse(enter.isAccepted())
        self.assertIn("Drop files tab", self.panel.status.text())
        self.assertNotIn("Must not become a paste", self.panel.paste.toPlainText())

    def test_file_drag_move_is_accepted_and_upload_preempts_listing(self):
        self.pump()
        self.panel.tabs.setCurrentIndex(1)
        source = Path(self.temp.name) / "local.txt"
        source.write_text("SYNTHETIC FILE", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source))])
        self.panel._last_poll = 0
        self.panel._tick()
        self.assertEqual(self.panel.pending["operation"], "list")
        self.assertTrue(self.panel.drop.isEnabled())
        for target in (self.panel.drop, self.panel.choose_files, self.panel.tabs.widget(1)):
            for kind in (QDragEnterEvent, QDragMoveEvent):
                event = kind(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(target, event)
                self.assertTrue(event.isAccepted(), f"{target.objectName()} {kind.__name__}")
        self.assertIn("release to upload", self.panel.drop.text())
        drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.panel.choose_files, drop)
        self.assertTrue(drop.isAccepted())
        deadline = time.monotonic() + 5
        while self.panel._job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.pump()
        self.assertEqual(self.store.listing()["total_items"], 1)
        self.assertIn("Saved encrypted", self.panel.drop.text())

    def test_cancel_discards_unpublished_upload_and_ignores_late_reply(self):
        self.pump()
        self.panel.paste.setPlainText("keep draft")
        self.panel.send_text.click()
        old_request_id = self.panel.pending["id"]
        self.panel.cancel.click()
        self.pump()
        self.assertIsNone(self.panel.pending)
        self.assertIsNone(self.panel.transfer)
        self.assertEqual(self.store.listing()["total_items"], 0)
        self.assertEqual(self.panel.paste.toPlainText(), "keep draft")

    def test_clipboard_expiry_never_erases_a_later_clipboard(self):
        upload(self.store, b"test text")
        self.pump()
        self.select_first()
        self.panel.copy.click()
        marker = bytes(QApplication.clipboard().mimeData().data("application/x-phoenix-drop-vault"))
        QApplication.clipboard().setText("new unrelated clipboard")
        _expire_clipboard(marker)
        self.assertEqual(QApplication.clipboard().text(), "new unrelated clipboard")
        self.panel.copy.click()
        marker = bytes(QApplication.clipboard().mimeData().data("application/x-phoenix-drop-vault"))
        _expire_clipboard(marker)
        self.assertEqual(QApplication.clipboard().text(), "")

    def test_real_background_local_read_and_explicit_export(self):
        self.pump()
        source = Path(self.temp.name) / "fixture.bin"
        source.write_bytes(b"TEST FILE")
        self.panel._queue_files([str(source)])
        deadline = time.monotonic()+5
        while self.panel._job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertIsNone(self.panel._job)
        self.pump()
        self.select_first()
        target = Path(self.temp.name) / "export.bin"
        with patch("matrix_gui.core.panel.custom_panels.drop_vault.drop_vault.QFileDialog.getSaveFileName",
                   return_value=(str(target), "")):
            self.panel.copy_file.click()
        deadline = time.monotonic()+5
        while self.panel._job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertEqual(target.read_bytes(), b"TEST FILE")
        self.assertEqual(Path(QApplication.clipboard().mimeData().urls()[0].toLocalFile()), target)
        self.assertTrue(self.panel.drag.isEnabled())

    def test_drop_feedback_waits_for_commit_and_ignores_immediate_repeat(self):
        self.pump()
        source = Path(self.temp.name) / "synthetic.txt"
        source.write_text("first version", encoding="utf-8")
        self.panel._queue_files([str(source)])
        self.assertIn("Reading", self.panel.drop.text())
        self.panel._queue_files([str(source)])
        self.assertIn("already running", self.panel.drop.text())
        deadline = time.monotonic() + 5
        while self.panel._job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertIsNone(self.panel._job)
        self.assertIn("Uploading", self.panel.drop.text())
        self.assertEqual(self.store.listing()["total_items"], 0)
        self.pump()
        self.assertIn("Saved encrypted", self.panel.drop.text())
        self.assertEqual(self.store.listing()["total_items"], 1)

        self.panel._queue_files([str(source)])
        deadline = time.monotonic() + 5
        while self.panel._job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertIn("Repeat drop ignored", self.panel.drop.text())
        self.assertEqual(self.panel.bus.queue, [])
        self.assertEqual(self.store.listing()["total_items"], 1)

        source.write_text("changed version", encoding="utf-8")
        self.panel._queue_files([str(source)])
        deadline = time.monotonic() + 5
        while self.panel._job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.pump()
        self.assertEqual(self.store.listing()["total_items"], 2)

    def test_metadata_registers_real_panel_service_and_persistent_constraint(self):
        meta = json.loads((ROOT / "phoenix/agents_meta/drop_vault.json").read_text(encoding="utf-8"))
        self.assertIn({"persistent_state": None}, meta["constraints"])
        self.assertEqual(meta["config"]["ui"]["panel"], ["drop_vault.drop_vault"])
        self.assertEqual(meta["config"]["service-manager"][0]["role"], ["hive.drop_vault.request@cmd_request"])

    def test_real_cockpit_loader_caches_per_agent_not_just_panel_type(self):
        from PyQt6.QtWidgets import QWidget
        import types
        source = ROOT / "phoenix/matrix_gui/core/session_window.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "_load_custom_panel")
        scope = {"emit_gui_exception_log": Mock()}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), "exec"), scope)
        host = QWidget()
        host.session_id, host.bus, host._panel_cache = "session", Bus(), {}
        loader = types.MethodType(scope["_load_custom_panel"], host)
        first = loader("drop_vault.drop_vault", {"universal_id": "drop-one"})
        second = loader("drop_vault.drop_vault", {"universal_id": "drop-two"})
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNot(first, second)
        self.assertEqual(first.agent_uid, "drop-one")
        self.assertEqual(second.agent_uid, "drop-two")
        self.assertIs(loader("drop_vault.drop_vault", {"universal_id": "drop-one"}), first)
        first.close()
        second.close()
        host.deleteLater()
        self.app.processEvents()

    def test_maximum_metadata_pages_and_chunks_fit_existing_packet_guards(self):
        from Crypto.PublicKey import RSA
        from core.python_core.utils.crypto_utils import encrypt_with_ephemeral_aes
        from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size
        # Worst permitted ordinary strings, not a tiny happy-path response.
        entry = None
        data = b"x"*CHUNK_BYTES
        for _ in range(20):
            entry = upload(self.store, data, kind="file", filename="f"*255, title="t"*256, notes="n"*4096)
        public_key = RSA.generate(2048).publickey().export_key().decode()
        for content in (self.store.listing(), self.store.read(entry["id"], 0)):
            content.update(token="t"*128, request_id="r"*128, agent_uid="a"*128, ok=True)
            inner = {"handler": "drop_vault.result", "content": content}
            diagnostics = []
            self.assertTrue(guard_packet_size(inner, diagnostics.append), diagnostics)
            sealed = encrypt_with_ephemeral_aes(inner, public_key)
            self.assertTrue(guard_packet_size({"handler": "cmd_rpc_route", "content": sealed}, diagnostics.append), diagnostics)

    def test_tampered_download_is_never_copyable(self):
        entry = upload(self.store, b"good")
        self.pump()
        self.panel.listing.setCurrentItem(self.panel.listing.topLevelItem(0))
        request = self.panel.bus.queue.pop()
        self.panel._callback(self.panel.session_id, payload={"content": dict(
            ok=True, agent_uid="drop-a", token=self.panel.token, request_id=request["request_id"],
            operation="read", entry=entry, offset=0, data=base64.b64encode(b"evil").decode(), eof=True)})
        self.app.processEvents()
        self.assertIsNone(self.panel.loaded)
        self.assertFalse(self.panel.copy.isEnabled())
        self.assertFalse(self.panel.save.isEnabled())


if __name__ == "__main__":
    unittest.main()
