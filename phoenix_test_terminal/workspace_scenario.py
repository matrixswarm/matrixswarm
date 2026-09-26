"""Workspace/graph/registry integration with real vault persistence, no deployment."""
from copy import deepcopy
import json
import time
import threading
from pathlib import Path
from unittest.mock import patch

from .registry_scenario import ScenarioFailure
from .vault_scenario import PASSWORD

_application = None


def run(stage, sandbox):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QInputDialog, QToolButton
    from matrix_gui.core.event_bus import EventBus
    from matrix_gui.modules.vault.vault_service import VaultService
    from matrix_gui.modules.vault.services import vault_service_loader
    from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
    from matrix_gui.swarm_workspace import workspace_manager as wm
    from matrix_gui.swarm_workspace import swarm_workspace as sw
    from matrix_gui.registry.registry_manager import RegistryManagerDialog
    from matrix_gui.swarm_workspace.panels.constraints.constraint_row_widget import ConstraintRowWidget

    global _application
    app = _application = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    vault = Path(sandbox) / "test-vault.json"
    expected_file = Path(sandbox) / "expected-workspace.json"
    checks, failures = [], []

    def check(condition, label):
        (checks if condition else failures).append(label)

    def disk():
        return VaultService.load_vault(str(vault), PASSWORD)

    def finish_save(graph):
        deadline = time.monotonic() + 15
        while graph._saving and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        if graph._saving:
            raise RuntimeError("Background save did not finish within test deadline")

    def initialize():
        EventBus.clear()
        vault_service_loader.initialize()
        VaultService.initialize_runtime(disk(), PASSWORD, str(vault))
        return VaultCoreSingleton.get()

    with patch.object(QMessageBox, "warning"), patch.object(QMessageBox, "critical"), patch.object(QMessageBox, "information"), \
         patch.object(wm, "emit_gui_exception_log") as manager_errors, patch.object(sw, "emit_gui_exception_log") as graph_errors:
        core = initialize()
        if stage == "editor-validation":
            from matrix_gui.swarm_workspace.cls_lib.agent.agent_node import AgentNode
            from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.sora import Sora
            from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.oracle import Oracle
            def node_for(name):
                return AgentNode(json.loads((root / "phoenix/agents_meta" / f"{name}.json").read_text(encoding="utf-8")))
            for field, value in (("duration", ""), ("duration", "not-a-number"), ("poll", ""), ("poll", "1.5")):
                node = node_for("sora")
                editor = Sora(node)
                before = deepcopy(node.config)
                getattr(editor, field).setText(value)
                caught = None
                with patch.object(QMessageBox, "warning") as warning:
                    try:
                        editor.save_btn.click()
                    except Exception as exc:
                        caught = type(exc).__name__
                    check(caught is None, f"Sora {field}={value!r}: invalid input must not escape handler ({caught})")
                    check(warning.called, f"Sora {field}={value!r}: invalid input must show validation warning")
                check(node.config == before and editor.result() != QDialog.DialogCode.Accepted, f"Sora {field}={value!r}: invalid save retains unchanged config and open dialog")
                editor.duration.setText("12")
                editor.poll.setText("60")
                editor.save_btn.click()
                check(editor.result() == QDialog.DialogCode.Accepted and node.config["duration"] == 12 and node.config["poll_interval"] == 60, f"Sora {field}: corrected input can be saved after rejection")
                editor.deleteLater()
            for name, editor_class in (("oracle", Oracle), ("sora", Sora)):
                node = node_for(name)
                node.config["model"] = "lab-saved-model-not-in-dropdown"
                editor = editor_class(node)
                check(editor.model.currentText() == node.config["model"], f"{name}: opening preserves unknown saved model selection")
                editor._save()
                check(node.config["model"] == "lab-saved-model-not-in-dropdown", f"{name}: untouched Save must not silently replace unknown model")
                editor.deleteLater()
            for name, editor_class, key, field, value in (
                ("sora", Sora, "resolution", "res", "lab-custom-resolution"),
                ("oracle", Oracle, "response_mode", "response_mode", "lab-custom-mode"),
            ):
                node = node_for(name)
                node.config[key] = value
                editor = editor_class(node)
                check(getattr(editor, field).currentText() == value, f"{name}: unknown {key} displayed without substitution")
                editor._save()
                check(node.config[key] == value, f"{name}: unknown {key} preserved on untouched Save")
                editor.deleteLater()
            from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.harvester import Harvester
            for name, editor_class, key, value in (
                ("oracle", Oracle, "temperature", 0.125),
                ("harvester", Harvester, "check_interval_sec", 3601),
                ("harvester", Harvester, "matrixd_timeout_sec", 301),
            ):
                node = node_for(name)
                node.config[key] = value
                before = deepcopy(node.config)
                editor = editor_class(node)
                editor.cancel_btn.click()
                check(node.config == before, f"{name} Cancel preserves original {key}={value}")
                editor.deleteLater()
                editor = editor_class(node)
                with patch.object(QMessageBox, "warning") as warning:
                    editor.save_btn.click()
                    preserved = node.config[key] == value
                    rejected = editor.result() != QDialog.DialogCode.Accepted and warning.called and node.config == before
                    check(preserved or rejected, f"{name} untouched {key}={value} must be preserved or visibly rejected, not silently changed to {node.config[key]}")
                editor.deleteLater()
            for name, editor_class, key, field, default, corrected in (
                ("oracle", Oracle, "temperature", "temperature", 0, 0.375),
                ("harvester", Harvester, "check_interval_sec", "interval", 30, 97),
                ("harvester", Harvester, "matrixd_timeout_sec", "timeout", 60, 80),
            ):
                for invalid in (None, "bad-number", {}, [], True, -1):
                    node = node_for(name)
                    node.config[key] = invalid
                    before = deepcopy(node.config)
                    editor = editor_class(node)
                    check(node.config == before, f"{name} {key}={invalid!r}: opening is nonmutating")
                    with patch.object(QMessageBox, "warning") as warning:
                        editor.save_btn.click()
                        check(warning.called and editor.result() != QDialog.DialogCode.Accepted and node.config == before,
                              f"{name} {key}={invalid!r}: invalid saved number visibly rejected without changes")
                    getattr(editor, field).setValue(corrected)
                    editor.save_btn.click()
                    check(editor.result() == QDialog.DialogCode.Accepted and node.config[key] == corrected,
                          f"{name} {key}={invalid!r}: corrected retry saves")
                    editor.deleteLater()
                node = node_for(name)
                node.config.pop(key, None)
                before = deepcopy(node.config)
                editor = editor_class(node)
                editor.cancel_btn.click()
                check(node.config == before, f"{name} missing {key}: Cancel leaves field absent")
                editor.deleteLater()
                editor = editor_class(node)
                editor.save_btn.click()
                check(node.config[key] == default, f"{name} missing {key}: Save uses documented default")
                editor.deleteLater()
            for name, editor_class, key, field in (
                ("oracle", Oracle, "model", "model"),
                ("oracle", Oracle, "response_mode", "response_mode"),
                ("sora", Sora, "model", "model"),
                ("sora", Sora, "resolution", "res"),
            ):
                for value in (None, 7, True, [], {}, ""):
                    node = node_for(name)
                    node.config[key] = value
                    before = deepcopy(node.config)
                    try:
                        editor = editor_class(node)
                    except Exception as exc:
                        check(False, f"{name} malformed {key}={value!r}: constructor raised {type(exc).__name__}")
                        continue
                    with patch.object(QMessageBox, "warning") as warning:
                        editor.save_btn.click()
                        check(warning.called and editor.result() != QDialog.DialogCode.Accepted and node.config == before,
                              f"{name} malformed {key}={value!r}: reject without mutation")
                    getattr(editor, field).setCurrentIndex(0)
                    editor.save_btn.click()
                    check(editor.result() == QDialog.DialogCode.Accepted and isinstance(node.config[key], str) and bool(node.config[key]),
                          f"{name} {key}: explicit valid selection permits retry")
                    editor.deleteLater()
            for name, editor_class in (("oracle", Oracle), ("sora", Sora)):
                for value in (None, {}, "bad", [], [{}], [None], [{"role": None}], [{"role": "hive.testing"}], [{"role": [7]}], [{"role": [], "priority": 17}], [{"role": ["hive.testing"]}, None]):
                    node = node_for(name)
                    node.config["service-manager"] = deepcopy(value)
                    before = deepcopy(node.config)
                    try:
                        editor = editor_class(node)
                    except Exception as exc:
                        check(False, f"{name} services={value!r}: constructor raised {type(exc).__name__}")
                        continue
                    check(node.config == before, f"{name} services={value!r}: opening does not mutate")
                    editor.cancel_btn.click()
                    check(node.config == before, f"{name} services={value!r}: Cancel preserves original")
                    editor.deleteLater()
                    editor = editor_class(node)
                    editor.save_btn.click()
                    check(node.config["service-manager"] == value,
                          f"{name} services={value!r}: untouched save preserves metadata exactly")
                    editor.deleteLater()
            for name, editor_class, key, field, boolean in (
                ("sora", Sora, "water_mark_text", "watermark_text", False),
                ("sora", Sora, "video_output_path", "video_path", False),
                ("sora", Sora, "thumbnail_output_path", "thumb_path", False),
                ("harvester", Harvester, "alert_to_role", "alert_role", False),
                ("sora", Sora, "watermark_enabled", "watermark_enabled", True),
                ("harvester", Harvester, "enabled", "enabled", True),
            ):
                values = (None, "false", "true", 0, 1, [], {}) if boolean else (None, 7, True, [], {})
                for value in values:
                    node = node_for(name)
                    node.config[key] = value
                    before = deepcopy(node.config)
                    try:
                        editor = editor_class(node)
                    except Exception as exc:
                        check(False, f"{name} {key}={value!r}: opens safely ({type(exc).__name__})")
                        continue
                    editor.cancel_btn.click()
                    check(node.config == before, f"{name} {key}={value!r}: Cancel unchanged")
                    editor.deleteLater()
                    editor = editor_class(node)
                    with patch.object(QMessageBox, "warning") as warning:
                        editor.save_btn.click()
                        check(warning.called and editor.result() != QDialog.DialogCode.Accepted and node.config == before,
                              f"{name} {key}={value!r}: invalid Save rejected atomically")
                    widget = getattr(editor, field)
                    if boolean:
                        widget.setChecked(False)
                    else:
                        widget.setText("lab-corrected")
                    editor.save_btn.click()
                    check(editor.result() == QDialog.DialogCode.Accepted and node.config[key] == (False if boolean else "lab-corrected"),
                          f"{name} {key}={value!r}: explicit correction saves")
                    editor.deleteLater()
                for value in ((False, True) if boolean else ("", "lab-value", "C:/lab path/影片")):
                    node = node_for(name)
                    node.config[key] = value
                    editor = editor_class(node)
                    editor.save_btn.click()
                    check(editor.result() == QDialog.DialogCode.Accepted and node.config[key] == value,
                          f"{name} valid {key}={value!r}: round trips")
                    editor.deleteLater()
            from matrix_gui.swarm_workspace.agent_item import AgentItem
            from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.base_editor import BaseEditor
            from PyQt6.QtGui import QPixmap, QPainter
            from types import SimpleNamespace
            for config in (None, [], "bad", {"ui": None}, {"ui": []}, {"ui": {"agent_tree": None}}, {"ui": {"agent_tree": {"emoji": []}}}):
                node = node_for("sora")
                node.config = deepcopy(config)
                item = AgentItem(node)
                canvas = QPixmap(200, 100)
                painter = QPainter(canvas)
                try:
                    item.paint(painter, None)
                    check(node.config == config, f"Malformed nested UI {config!r}: paint succeeds without mutation")
                except Exception as exc:
                    check(False, f"Malformed nested UI: paint raised {type(exc).__name__}")
                finally:
                    painter.end()
            node = node_for("oracle")
            node.config = {"value": "original"}
            class FailingEditor(BaseEditor):
                fail = True
                def _save(self):
                    if self.fail:
                        self.node.config["value"] = "partial"
                        self.node.mark_dirty()
                        raise RuntimeError("SENSITIVE-TEST-MARKER")
                    super()._save()
            editor = FailingEditor(node)
            with patch.object(QMessageBox, "critical") as critical, patch("matrix_gui.swarm_workspace.cls_lib.agent.config_editors.base_editor.logging.getLogger") as logger:
                editor.save_btn.click()
                check(node.config == {"value": "original"} and not node._dirty, "Unexpected Save error rolls back config and dirty flag")
                check(critical.called and "SENSITIVE-TEST-MARKER" not in str(critical.call_args), "Save failure visibly reported without raw exception contents")
                diagnostic = str(logger.return_value.error.call_args)
                check(logger.return_value.error.called and "workspace_scenario.py" in diagnostic and "RuntimeError" in diagnostic and "SENSITIVE-TEST-MARKER" not in diagnostic,
                      "Unexpected failure logs stack locations and type without exception payload")
            editor.fail = False
            editor.inputs["value"].setText("corrected")
            editor.save_btn.click()
            check(node.config["value"] == "corrected" and editor.result() == QDialog.DialogCode.Accepted, "Save retry works after unexpected exception")
            editor.deleteLater()
            for failure in (ImportError("SENSITIVE-TEST-MARKER"), AttributeError("SENSITIVE-TEST-MARKER")):
                node = node_for("oracle")
                before = deepcopy(node.config)
                item = AgentItem(node)
                with patch("matrix_gui.swarm_workspace.agent_item.importlib.import_module", side_effect=failure), patch.object(QMessageBox, "critical") as critical:
                    item.mouseDoubleClickEvent(None)
                    check(critical.called and node.config == before, "Broken editor import reports failure instead of generic fallback")
            node = node_for("oracle")
            before = deepcopy(node.config)
            def broken_constructor(node, parent=None):
                node.config["partial"] = True
                node.mark_dirty()
                raise TypeError("SENSITIVE-TEST-MARKER")
            item = AgentItem(node)
            with patch("matrix_gui.swarm_workspace.agent_item.importlib.import_module", return_value=SimpleNamespace(Oracle=broken_constructor)), patch.object(QMessageBox, "critical") as critical:
                item.mouseDoubleClickEvent(None)
                check(critical.called and node.config == before and not node._dirty, "Constructor exception rolls back partial configuration")
            from matrix_gui.modules.vault.services.workspace_writer import WorkspaceWriter
            gui_thread = threading.get_ident()
            deliveries = []
            writer = WorkspaceWriter(lambda error: deliveries.append((threading.get_ident(), error)))
            thread = threading.Thread(target=lambda: writer.completed.emit(None))
            thread.start()
            thread.join(2)
            check(not deliveries, "Worker completion waits for GUI event processing")
            app.processEvents()
            check(deliveries == [(gui_thread, None)], "Writer completion is delivered on GUI thread")
            writer.deleteLater()
            rejected = []
            def wrong_thread_save():
                try:
                    core.save_workspace_async({"uuid": "wrong-thread"}, lambda _: None)
                except RuntimeError:
                    rejected.append(True)
            thread = threading.Thread(target=wrong_thread_save)
            thread.start()
            thread.join(2)
            check(rejected == [True] and not core._workspace_queue and core._workspace_active is None,
                  "Wrong-thread save rejected before queue mutation")
            from unittest.mock import Mock
            core._workspace_writer = Mock()
            def broken_completion(success):
                raise RuntimeError("SENSITIVE-CALLBACK-MARKER")
            results = []
            core.save_workspace_async({"uuid": "first"}, broken_completion)
            core.save_workspace_async({"uuid": "second"}, results.append)
            try:
                VaultCoreSingleton.initialize(core.read(), PASSWORD, str(vault))
                check(False, "Vault replacement must wait for pending writes")
            except RuntimeError:
                check(VaultCoreSingleton.get() is core and not core._closed,
                      "Pending writes prevent vault replacement without changing active vault")
            with patch("matrix_gui.modules.vault.services.vault_core_singleton.logging.getLogger") as logger:
                core._workspace_written(None)
                check(logger.return_value.error.called and "SENSITIVE-CALLBACK-MARKER" not in str(logger.return_value.error.call_args),
                      "Broken completion callback logs safe diagnostics instead of escaping Qt")
            check(core._workspace_active[0]["uuid"] == "second", "Broken completion does not stall next queued save")
            core._workspace_written(None)
            check(results == [True] and core._workspace_active is None, "Next completion succeeds after callback failure")
            for entry in (None, {}, {"uuid": []}, {"uuid": ""}):
                try:
                    core.save_workspace_async(entry, results.append)
                    check(False, f"Invalid workspace entry {entry!r}: rejected before queuing")
                except (ValueError, TypeError):
                    check(not core._workspace_queue and core._workspace_active is None,
                          f"Invalid workspace entry {entry!r}: no stranded queue state")
                except Exception as exc:
                    check(False, f"Invalid workspace entry {entry!r}: unclassified {type(exc).__name__}")
            # Already accepted writes drain to the original vault after Close.
            core._workspace_queue.clear()
            core._workspace_active = None
            results.clear()
            core.save_workspace_async({"uuid": "close-first"}, results.append)
            core.save_workspace_async({"uuid": "close-second"}, results.append)
            EventBus.emit("vault.closed")
            with patch.object(EventBus, "emit") as emitted:
                core._workspace_written(OSError("test disk failure"))
                core._workspace_written(None)
                check(not emitted.called, "Closed vault completions do not broadcast into active UI")
            check(results == [False, True] and core._workspace_active is None and not core._workspace_queue,
                  "Close drains accepted queue despite first write failure")
            check("close-first" not in core.data["workspaces"] and "close-second" in core.data["workspaces"],
                  "Only successful closed-vault write is published internally")
            try:
                core.save_workspace_async({"uuid": "too-late"}, results.append)
                check(False, "Closed vault rejects new write")
            except RuntimeError:
                check(True, "Closed vault rejects new write")
        elif stage == "create":
            manager = wm.WorkspaceManagerDialog()
            opened = []
            manager.workspace_selected.connect(opened.append)
            manager.new_btn.click()
            check(len(opened) == 1, "New workspace emits one open signal")
            if not opened:
                raise ScenarioFailure(checks, failures + ["Workspace creation blocked"])
            uid = opened[0]
            record = disk()["workspaces"][uid]
            check(record["uuid"] == uid and record["data"][0]["name"] == "matrix", "Workspace and Matrix root persisted")
            check(record["data"][0]["parent"] is None, "Matrix root has no parent")
            before, ciphertext = deepcopy(core.read()), vault.read_bytes()
            with patch.object(QInputDialog, "getText", return_value=("CANCELED", False)):
                manager.rename_btn.click()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                manager.delete_btn.click()
            check(core.read() == before and vault.read_bytes() == ciphertext, "Canceled rename/delete leave runtime and disk unchanged")
            with patch.object(QInputDialog, "getText", return_value=("LAB WORKSPACE", True)):
                manager.rename_btn.click()
            check(disk()["workspaces"][uid]["label"] == "LAB WORKSPACE", "Rename survives real vault save")
            manager.clone_btn.click()
            clones = set(disk()["workspaces"]) - {uid}
            check(len(clones) == 1, "Clone persists one independent workspace")
            if len(clones) == 1:
                clone_uid = clones.pop()
                clone = disk()["workspaces"][clone_uid]
                check(clone["uuid"] == clone_uid and clone["data"] == disk()["workspaces"][uid]["data"], "Clone preserves graph with a new workspace identity")
                manager._select_workspace(clone_uid)
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                    manager.delete_btn.click()
                check(set(disk()["workspaces"]) == {uid}, "Confirmed delete removes only the clone from the saved vault")
            expected_file.write_text(json.dumps({"uid": uid}), encoding="utf-8")
        elif stage in {"assign", "reopen"}:
            uid = json.loads(expected_file.read_text(encoding="utf-8"))["uid"]
            record = deepcopy(core.read()["workspaces"][uid])
            graph = sw.SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=record)
            check(not graph_errors.called and graph.layout() is not None, "Actual graph editor fully initializes")
            check(bool(graph.controller.nodes), "Actual graph loader restores Matrix node")
            item = next(iter(graph.controller.nodes.values()))
            serial = next(iter(core.read()["registry"]["ssh"]))
            if stage == "assign":
                # Fixture adds an unassigned SSH requirement; assignment itself
                # uses the production row button and real class-locked registry.
                constraint = {"class": "ssh", "serial": None, "met": False, "auto": False, "required": False, "raw": {}}
                item.node.constraints.append(constraint)
                changed = []
                row = ConstraintRowWidget(constraint, lambda _: None, lambda _: None, lambda: changed.append(True))
                original_exec = QDialog.exec
                def drive(dialog):
                    def choose():
                        dialog.tabs.currentWidget().setCurrentRow(1)
                        dialog.assign_btn.click()
                    QTimer.singleShot(0, choose)
                    return original_exec(dialog)
                with patch.object(RegistryManagerDialog, "exec", drive):
                    row.findChild(QToolButton).click()
                check(constraint["serial"] == serial and constraint["met"] and changed == [True], "Real assignment button links saved SSH profile to graph node")
                graph.save()
                finish_save(graph)
                saved = disk()["workspaces"][uid]["data"][0]["constraints"]
                check(any(c.get("serial") == serial and c["class"] == "ssh" for c in saved), "Graph serializer persists registry reference")
            else:
                check(any(c.get("serial") == serial and c["class"] == "ssh" for c in item.node.constraints), "SSH assignment survives interpreter and graph restart")
                check(record["label"] == "LAB WORKSPACE", "Workspace label survives restart")
            graph.close()
            finish_save(graph)
        elif stage == "graph-failure":
            from PyQt6.QtGui import QCloseEvent
            from PyQt6 import sip
            uid = json.loads(expected_file.read_text(encoding="utf-8"))["uid"]
            for lifecycle in ("deleted", "closed", "switched"):
                core = initialize()
                record = deepcopy(core.read()["workspaces"][uid])
                graph = sw.SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=record)
                graph.workspace_data["label"] = "LATE CALLBACK TEST"
                callbacks = []
                with patch.object(core, "save_workspace_async", side_effect=lambda entry, cb: callbacks.append(cb)):
                    graph.save()
                check(len(callbacks) == 1, f"{lifecycle}: pending save captured")
                if lifecycle == "deleted":
                    sip.delete(graph)
                    callbacks[0](True)
                    check(True, "Late completion safely ignores deleted Qt dialog")
                else:
                    if lifecycle == "closed":
                        EventBus.emit("vault.closed")
                    else:
                        initialize()
                    callbacks[0](True)
                    check(not graph._saving and "Vault closed or changed" in graph.save_status.text(),
                          f"{lifecycle}: late completion reports inactive vault without resaving")
                    with patch.object(VaultCoreSingleton.get(), "save_workspace_async") as submit:
                        check(graph.save() is False and not submit.called,
                              f"{lifecycle}: old workspace cannot write into current vault")
                    sip.delete(graph)
            for closing in (False, True):
                for raises in (False, True):
                    core = initialize()
                    graph_errors.reset_mock()
                    record = deepcopy(core.read()["workspaces"][uid])
                    graph = sw.SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=record)
                    check(not graph_errors.called and bool(graph.controller.nodes), "Failure probe uses initialized real graph")
                    graph.workspace_data["label"] = f"UNSAVED close={closing} exception={raises}"
                    before, ciphertext = deepcopy(core.read()), vault.read_bytes()
                    event = QCloseEvent()
                    tag = f"Graph close={closing} exception={raises}"
                    # Exercise real worker disk errors and queue-submission errors.
                    target, method = (vault_service_loader, "save_vault_singlefile") if raises else (core, "save_workspace_async")
                    with patch.object(target, method, side_effect=OSError("Synthetic write failure")), \
                         patch.object(QMessageBox, "critical") as critical, patch.object(QMessageBox, "warning") as warning:
                        try:
                            if closing:
                                graph.closeEvent(event)
                            else:
                                graph.save()
                            finish_save(graph)
                        except Exception as exc:
                            failures.append(f"{tag}: uncaught {type(exc).__name__} escapes save handler")
                        check("Save failed" in graph.save_status.text(), f"{tag}: failed save visibly reported")
                    check(core.read() == before, f"{tag}: committed live vault unchanged")
                    check(vault.read_bytes() == ciphertext, f"{tag}: encrypted file unchanged")
                    if closing:
                        check(not event.isAccepted(), f"{tag}: failed save prevents closing")
                    check(graph.workspace_data["label"].startswith("UNSAVED"), f"{tag}: editor retains pending edit")
                    # Retry the same editor after restoring normal persistence.
                    graph.save()
                    finish_save(graph)
                    check(disk()["workspaces"][uid]["label"] == graph.workspace_data["label"], f"{tag}: retry persists pending edit")
                    graph.deleteLater()
            # A deliberately blocked disk writer must not block the GUI, and
            # completion of revision one must not erase revision two.
            core = initialize()
            graph = sw.SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=deepcopy(core.read()["workspaces"][uid]))
            entered, release = threading.Event(), threading.Event()
            real_write = vault_service_loader.save_vault_singlefile
            def delayed_write(*args, **kwargs):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("Test release never arrived")
                return real_write(*args, **kwargs)
            ticks = []
            timer = QTimer()
            timer.setInterval(5)
            timer.timeout.connect(lambda: ticks.append(1))
            timer.start()
            with patch.object(vault_service_loader, "save_vault_singlefile", delayed_write):
                try:
                    graph.workspace_data["label"] = "FIRST REVISION"
                    graph._slow_save_timer.setInterval(10)
                    graph.save()
                    deadline = time.monotonic() + 2
                    while (not entered.is_set() or len(ticks) < 3) and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(0.005)
                    check(entered.is_set() and len(ticks) >= 3 and graph._saving, "GUI heartbeat continues while disk writer is blocked")
                    check("please pause edits" in graph.save_status.text(), "Slow writer asks user to pause edits")
                    check(not core.patch("workspaces", {}), "Legacy write cannot race pending background snapshot")
                    graph.workspace_data["label"] = "LATEST REVISION"
                    graph.save()
                    check("please pause edits" in graph.save_status.text(), "Pending edits do not erase slow-write warning")
                    event = QCloseEvent()
                    graph.closeEvent(event)
                    check(not event.isAccepted(), "Close waits without blocking for pending revisions")
                    check("Saved" not in graph.save_status.text(), "Pending write is not reported as saved")
                finally:
                    release.set()
                finish_save(graph)
            timer.stop()
            check(disk()["workspaces"][uid]["label"] == "LATEST REVISION", "Newest revision survives delayed first completion and reload")
            check("Saved to Vault" in graph.save_status.text(), "Status confirms successful final write")
            # Fail the actual atomic replacement, after encryption/temp write.
            from matrix_gui.modules.vault.crypto import vault_handler
            graph._allow_close = False
            graph._close_requested = False
            ciphertext, before = vault.read_bytes(), core.read()
            graph.workspace_data["label"] = "RETRY AFTER DISK FAILURE"
            with patch.object(vault_handler.os, "replace", side_effect=OSError("Synthetic atomic replace failure")):
                graph.save()
                finish_save(graph)
            check(core.read() == before and vault.read_bytes() == ciphertext, "Atomic replace failure preserves committed memory and ciphertext")
            check("Save failed" in graph.save_status.text(), "Actual disk failure produces failed-write status")
            graph.retry_save_btn.click()
            finish_save(graph)
            check(disk()["workspaces"][uid]["label"] == "RETRY AFTER DISK FAILURE", "Retry button recovers from atomic replace failure")
            graph._ready_timer.start(10)
            deadline = time.monotonic() + 2
            while graph.save_status.text() != "Ready…" and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            check(graph.save_status.text() == "Ready…", "Saved status returns to Ready after confirmation pause")
            graph.deleteLater()
        elif stage == "graph-edits":
            uid = json.loads(expected_file.read_text(encoding="utf-8"))["uid"]
            graph = sw.SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=deepcopy(core.read()["workspaces"][uid]))
            # Seed two sibling agents, then exercise the release handler used
            # by drag-to-reparent (only the native event tail is replaced).
            from matrix_gui.swarm_workspace.autoplant import autoplant
            controller = graph.controller
            matrix_gid = controller.get_graph_id("matrix")
            siblings = []
            for name in ("harvester", "log_streamer"):
                meta = json.loads((root / "phoenix/agents_meta" / f"{name}.json").read_text(encoding="utf-8"))
                item = autoplant(graph.scene, meta)
                controller.register_item(item)
                item.node.set_parent(matrix_gid)
                siblings.append(item)
            graph.save()
            finish_save(graph)
            child, parent = siblings
            with patch.object(graph, "save", wraps=graph.save) as autosave:
                controller.dragging_item, controller.drop_target = child, parent
                with patch.object(controller, "_orig_mouse_release"):
                    controller._mouse_release(None)
                check(autosave.call_count == 1, "Reparent drop requests exactly one autosave")
                finish_save(graph)
                autosave.reset_mock()
                controller.reparent(child, parent)
                controller.reparent(parent, child)
                controller.reparent(child, child)
                check(autosave.call_count == 0, "Unchanged parent, cycle and self-parent do not request saves")
            restored = sw.SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=disk()["workspaces"][uid])
            check(restored.controller.nodes[child.node.get_graph_id()].node.get_parent() == parent.node.get_graph_id(), "Dropped parent survives encrypted-vault reload into new graph")
            restored.scene.clear()
            restored.controller.nodes.clear()
            restored.controller.edges.clear()
            restored.deleteLater()
            # Same shared method is used by the context menu.
            controller.reparent(child, controller.nodes[matrix_gid])
            finish_save(graph)
            check(next(n for n in disk()["workspaces"][uid]["data"] if n["graph_id"] == child.node.get_graph_id())["parent"] == matrix_gid, "Context-menu reparent path also persists automatically")
            # Identity rotation must preserve exact references and cancellation.
            old_parent_uid = parent.node.get_universal_id()
            child.node.config["test_reference"] = old_parent_uid
            graph.save()
            finish_save(graph)
            before_ids = {i.node.get_universal_id() for i in controller.nodes.values()}
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
                graph.inspector._generate_all_uids()
            check({i.node.get_universal_id() for i in controller.nodes.values()} == before_ids, "Canceled ID rotation leaves identities unchanged")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                graph.inspector._generate_all_uids()
            finish_save(graph)
            saved_nodes = disk()["workspaces"][uid]["data"]
            check(not before_ids.intersection({n["universal_id"] for n in saved_nodes}), "ID rotation automatically persists new identities")
            saved_child = next(n for n in saved_nodes if n["graph_id"] == child.node.get_graph_id())
            check(saved_child["config"]["test_reference"] == parent.node.get_universal_id(), "ID rotation persists updated cross-agent references")

            optional = {"class": "ssh", "raw": {}, "required": False, "auto": False, "met": False, "serial": None}
            child.node.constraints.append(optional)
            graph.inspector.load(child.node)
            graph.save()
            finish_save(graph)
            # Two same-label profiles ensure selection uses serial identity.
            core.get_store("registry").set_namespace("ssh", {
                serial: {"label": "LAB duplicate label", "host": "example.invalid", "serial": serial}
                for serial in ("lab-a", "lab-b")
            })
            optional.update(serial="lab-b", met=True)
            graph.inspector._reload_constraints()
            graph.save()
            finish_save(graph)
            def current_row():
                return next(graph.inspector.constraint_layout.itemAt(i).widget()
                            for i in range(graph.inspector.constraint_layout.count())
                            if getattr(graph.inspector.constraint_layout.itemAt(i).widget(), "constraint", None) is optional)
            original_exec = QDialog.exec
            def drive_picker(dialog, cancel=False):
                def choose():
                    check(dialog._current_selection() == ("ssh", "lab-b"), "Satisfied requirement picker highlights assigned serial, not duplicate label")
                    if cancel:
                        dialog.reject()
                    else:
                        dialog.tabs.currentWidget().setCurrentRow(1)
                        dialog.assign_btn.click()
                QTimer.singleShot(0, choose)
                return original_exec(dialog)
            with patch.object(RegistryManagerDialog, "exec", lambda dialog: drive_picker(dialog, True)), patch.object(graph, "save", wraps=graph.save) as autosave:
                current_row().findChild(QToolButton).click()
                check(autosave.call_count == 0 and optional["serial"] == "lab-b", "Canceling assignment preserves existing profile without saving")
            with patch.object(RegistryManagerDialog, "exec", drive_picker), patch.object(graph, "save", wraps=graph.save) as autosave:
                current_row().findChild(QToolButton).click()
                check(autosave.call_count == 1, "Assignment through actual inspector row requests autosave")
            finish_save(graph)
            saved_child = next(n for n in disk()["workspaces"][uid]["data"] if n["graph_id"] == child.node.get_graph_id())
            check(any(c.get("serial") == "lab-a" for c in saved_child["constraints"]), "Changed assignment survives vault reload without closing editor")
            missing = RegistryManagerDialog(class_lock="ssh", selected_serial="missing-profile")
            check(missing._current_selection() == (None, None), "Missing assigned serial does not highlight an unrelated profile")
            missing.deleteLater()
            with patch.object(graph, "save", wraps=graph.save) as autosave:
                graph.inspector._remove_constraint(optional)
                check(autosave.call_count == 1, "Requirement removal requests autosave")
            finish_save(graph)
            saved_child = next(n for n in disk()["workspaces"][uid]["data"] if n["graph_id"] == child.node.get_graph_id())
            check(optional not in saved_child["constraints"], "Requirement removal persists without closing editor")
            # Checkpoint explicitly after the probe so later tests are independent.
            graph.save()
            finish_save(graph)
            controller.reparent(child, parent)
            finish_save(graph)
            before_delete = vault.read_bytes()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), patch.object(graph, "save", wraps=graph.save) as autosave:
                controller.delete_node(parent)
                check(autosave.call_count == 0 and vault.read_bytes() == before_delete, "Canceled branch deletion does not save or change disk")
            removed = {child.node.get_graph_id(), parent.node.get_graph_id()}
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), patch.object(graph, "save", wraps=graph.save) as autosave:
                controller.delete_node(parent)
                check(autosave.call_count == 1, "Context-menu branch deletion requests autosave")
            app.processEvents()
            finish_save(graph)
            check(not removed.intersection({n["graph_id"] for n in disk()["workspaces"][uid]["data"]}), "Deleted branch is absent from saved vault without closing editor")
            graph.scene.clear()
            controller.nodes.clear()
            controller.edges.clear()
            graph.deleteLater()
        elif stage == "graph-config":
            from matrix_gui.swarm_workspace.autoplant import autoplant
            uid = json.loads(expected_file.read_text(encoding="utf-8"))["uid"]
            graph = sw.SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=deepcopy(core.read()["workspaces"][uid]))
            def add(name):
                meta = json.loads((root / "phoenix/agents_meta" / f"{name}.json").read_text(encoding="utf-8"))
                item = autoplant(graph.scene, meta)
                graph.controller.register_item(item)
                item.node.set_parent(graph.controller.get_graph_id("matrix"))
                return item
            def saved_config(item):
                return next(n["config"] for n in disk()["workspaces"][uid]["data"] if n["graph_id"] == item.node.get_graph_id())
            def edit(item, configure, cancel=False):
                import sys
                print(f"[config-probe] {item.node.get_name()} cancel={cancel}", file=sys.__stderr__, flush=True)
                original_exec = QDialog.exec
                def drive(dialog):
                    def interact():
                        try:
                            configure(dialog)
                            (dialog.cancel_btn if cancel else dialog.save_btn).click()
                        except Exception as exc:
                            failures.append(f"Configuration interaction failed: {exc}")
                            dialog.reject()
                    QTimer.singleShot(0, interact)
                    return original_exec(dialog)
                with patch.object(QDialog, "exec", drive):
                    item.mouseDoubleClickEvent(None)
                finish_save(graph)
            harvester = add("harvester")
            graph.save()
            finish_save(graph)
            before, ciphertext = deepcopy(harvester.node.config), vault.read_bytes()
            edit(harvester, lambda dlg: dlg.interval.setValue(97), cancel=True)
            check(harvester.node.config == before and vault.read_bytes() == ciphertext, "Harvester Cancel preserves config and encrypted bytes")
            edit(harvester, lambda dlg: dlg.interval.setValue(97))
            check(saved_config(harvester)["check_interval_sec"] == 97, "Harvester Save persists edited interval through agent double-click path")
            def verify_interval(dlg):
                check(dlg.interval.value() == 97, "Reopened Harvester editor restores saved interval")
            edit(harvester, verify_interval, cancel=True)

            https = add("matrix_https")
            services = [{"role": ["matrix_https.status@cmd_status"], "priority": 17, "exclusive": True, "scope": ["parent"], "auth": {"sig": True}}, {"role": ["lab.secondary"], "priority": 3}]
            https.node.config["service-manager"] = deepcopy(services)
            graph.save()
            finish_save(graph)
            before, ciphertext = deepcopy(https.node.config), vault.read_bytes()
            edit(https, lambda dlg: dlg.lockdown_time.setValue(123), cancel=True)
            check(https.node.config == before and vault.read_bytes() == ciphertext, "HTTPS Cancel preserves routing metadata and vault")
            edit(https, lambda dlg: dlg.lockdown_time.setValue(123))
            cfg = saved_config(https)
            check(cfg["lockdown_time"] == 123, "HTTPS Save persists edited lockdown duration")
            check(cfg["service-manager"] == services, "Changing HTTPS duration must preserve untouched service routing/auth metadata")

            generic = add("log_streamer")
            generic.node.config.update(lab_bool=False, lab_int=7, lab_float=1.5, lab_null=None, lab_text="hello")
            graph.save()
            finish_save(graph)
            before, ciphertext = deepcopy(generic.node.config), vault.read_bytes()
            edit(generic, lambda dlg: dlg.inputs["lab_text"].setText("canceled"), cancel=True)
            check(generic.node.config == before and vault.read_bytes() == ciphertext, "Generic editor Cancel leaves config and disk untouched")
            edit(generic, lambda dlg: dlg.inputs["lab_text"].setText("saved"))
            cfg = saved_config(generic)
            check(cfg["lab_text"] == "saved", "Generic editor persists edited text")
            for key in ("lab_bool", "lab_int", "lab_float", "lab_null"):
                check(type(cfg[key]) is type(before[key]) and cfg[key] == before[key], f"Generic editor preserves unchanged {key} value and type")
            from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.base_editor import BaseEditor
            for key, invalid in (("lab_bool", "maybe"), ("lab_int", "3.5"), ("lab_float", "nan"), ("lab_null", "typed without schema")):
                before_invalid = deepcopy(generic.node.config)
                editor = BaseEditor(generic.node, graph)
                editor.inputs["lab_text"].setText("MUST NOT LEAK")
                editor.inputs[key].setText(invalid)
                with patch.object(QMessageBox, "warning") as warning:
                    editor.save_btn.click()
                    check(warning.called and editor.result() != QDialog.DialogCode.Accepted and generic.node.config == before_invalid, f"Invalid {key} is rejected without partial config mutation")
                editor.deleteLater()
            def change_scalars(editor):
                editor.inputs["lab_bool"].setText("true")
                editor.inputs["lab_int"].setText("19")
                editor.inputs["lab_float"].setText("2.75")
                editor.inputs["lab_null"].setText("null")
            edit(generic, change_scalars)
            cfg = saved_config(generic)
            check(cfg["lab_bool"] is True and type(cfg["lab_int"]) is int and cfg["lab_int"] == 19 and cfg["lab_float"] == 2.75 and cfg["lab_null"] is None, "Valid scalar edits retain types through encrypted save")

            # Next batch: sibling role editors must preserve unrelated metadata.
            for name in ("matrix_websocket", "matrix_ssh", "telegram_relay",
                         "email_send", "discord_relay", "apache_watchdog",
                         "cdn_dozer", "matrix_email", "meta_blast", "oracle",
                         "sora", "storm_crow", "trend_scout", "tripwire_lite",
                         "uptime_sentinel", "wordpress_plugin_guard"):
                sibling = add(name)
                sibling.node.config["service-manager"] = deepcopy(services)
                graph.save()
                finish_save(graph)
                before_sibling, ciphertext = deepcopy(sibling.node.config), vault.read_bytes()
                edit(sibling, lambda dlg: None, cancel=True)
                check(sibling.node.config == before_sibling and vault.read_bytes() == ciphertext, f"{name} Cancel preserves config and disk")
                edit(sibling, lambda dlg: None)
                check(saved_config(sibling)["service-manager"] == services, f"{name} Save preserves service routing/auth metadata and secondary entries")
                if name in {"storm_crow", "email_send", "discord_relay", "telegram_relay", "wordpress_plugin_guard"}:
                    def add_role(dlg):
                        with patch.object(QInputDialog, "getText", return_value=("hive.testing", True)):
                            dlg._add_role()
                    ciphertext, before_role = vault.read_bytes(), deepcopy(sibling.node.config)
                    edit(sibling, add_role, cancel=True)
                    check(sibling.node.config == before_role and vault.read_bytes() == ciphertext, f"{name} Cancel discards role-list changes")
                    edit(sibling, add_role)
                    expected_services = deepcopy(services)
                    expected_services[0]["role"].append("hive.testing")
                    check(saved_config(sibling)["service-manager"] == expected_services, f"{name} Add Role preserves all other registration fields")
                    def remove_added(dlg):
                        dlg.roles_list.setCurrentRow(dlg.roles_list.count() - 1)
                        dlg._remove_role()
                    edit(sibling, remove_added)
                    check(saved_config(sibling)["service-manager"] == services, f"{name} Remove Role preserves other roles and registrations")
                if name == "wordpress_plugin_guard":
                    # Missing optional section is a legitimate fresh/legacy config.
                    sibling.node.config.pop("service-manager", None)
                    graph.save()
                    finish_save(graph)
                    before_missing, ciphertext = deepcopy(sibling.node.config), vault.read_bytes()
                    edit(sibling, lambda dlg: None, cancel=True)
                    check(sibling.node.config == before_missing and vault.read_bytes() == ciphertext, "WordPress Cancel must not insert missing service defaults into live config")
            graph.scene.clear()
            graph.controller.nodes.clear()
            graph.controller.edges.clear()
            graph.deleteLater()
        elif stage == "rejection":
            uid = json.loads(expected_file.read_text(encoding="utf-8"))["uid"]
            for operation, raises in ((op, fail) for op in ("new", "clone", "rename", "delete") for fail in (False, True)):
                core = initialize()
                manager = wm.WorkspaceManagerDialog()
                manager._select_workspace(uid)
                before, ciphertext = deepcopy(core.read()), vault.read_bytes()
                rows = [manager.ws_list.item(i).text() for i in range(manager.ws_list.count())]
                # Call the exact slot directly here so uncaught Qt exceptions
                # become diagnostics instead of terminating the entire worker.
                with patch.object(core, "patch", return_value=False, side_effect=RuntimeError("Synthetic save failure") if raises else None), \
                     patch.object(QInputDialog, "getText", return_value=("REJECTED RENAME", True)), \
                     patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                    try:
                        getattr(manager, f"_{operation}_workspace")()
                    except Exception as exc:
                        failures.append(f"Rejected {operation} escapes GUI slot with uncaught {type(exc).__name__}")
                check(vault.read_bytes() == ciphertext, f"Rejected {operation} leaves encrypted disk unchanged")
                check(core.read() == before, f"Rejected {operation} must not mutate live workspace data")
                check(rows == [manager.ws_list.item(i).text() for i in range(manager.ws_list.count())], f"Rejected {operation} preserves displayed workspace list (exception={raises})")
            core = initialize()
            store = core.get_store("workspaces")
            for method, args in (("get_workspace", (uid,)), ("list_workspaces", ())):
                try:
                    result = getattr(store, method)(*args)
                    check(bool(result), f"WorkspaceStore.{method} reads saved workspace")
                except Exception as exc:
                    failures.append(f"WorkspaceStore.{method} raised {type(exc).__name__}: {exc}")
        else:
            raise ValueError("Unknown workspace stage")
        if stage not in {"rejection", "graph-failure"}:
            check(not manager_errors.called and not graph_errors.called, "No unexpected workspace construction/handler errors")
    app.processEvents()
    # Complete deleteLater while QApplication is still alive; otherwise Qt
    # graphics effects can be destroyed after their application on worker exit.
    from PyQt6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if failures:
        raise ScenarioFailure(checks, failures)
    return checks
