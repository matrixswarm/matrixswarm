"""Full source cockpit smoke test; no AST substitution or live credentials."""
import builtins
import importlib.util
import time
import threading
from pathlib import Path
from unittest.mock import patch
from .vault_scenario import PASSWORD
from .registry_scenario import ScenarioFailure

_application = None


def run(stage, sandbox):
    global _application
    from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
    from PyQt6.QtCore import QTimer
    _application = QApplication.instance() or QApplication([])
    checks, failures = [], []
    def check(condition, description):
        (checks if condition else failures).append(description)
    vault = Path(sandbox) / "cold-start-vault.json"
    root = Path(__file__).resolve().parents[1]
    original_print = builtins.print
    try:
        spec = importlib.util.spec_from_file_location("phoenix_cold_start_app", root / "phoenix/phoenix.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(QMessageBox, "critical") as critical, patch.object(QMessageBox, "warning") as warning, \
             patch.object(QMessageBox, "information"), \
             patch.object(QFileDialog, "getSaveFileName", return_value=(str(vault), "")), \
             patch.object(QFileDialog, "getOpenFileName", return_value=(str(vault), "")):
            cockpit = module.PhoenixCockpit()
            check(cockpit.stack.currentIndex() == 0, "Complete cockpit starts locked")
            check(bool(cockpit.control_panel) and cockpit.tab_stack.count() == 1, "Complete cockpit builds controls and dashboard")
            with patch.object(module.VaultSelectorDialog, "exec", return_value=QDialog.DialogCode.Rejected):
                cockpit.unlock_button.click()
            check(cockpit.stack.currentIndex() == 0, "Cancel before unlock leaves cockpit locked")
            def select(dialog):
                QTimer.singleShot(0, (dialog.create_btn if stage == "create" else dialog.unlock_btn).click)
                return QDialog.exec(dialog)
            def create(dialog):
                def action():
                    dialog.password_input.setText(PASSWORD)
                    dialog.create_btn.click()
                    if dialog.result() != QDialog.DialogCode.Accepted:
                        dialog.reject()
                QTimer.singleShot(0, action)
                return QDialog.exec(dialog)
            def unlock(dialog):
                def action():
                    check(not dialog.optional_capabilities.isHidden(), "Login capabilities are always expanded")
                    dialog.vault_path = str(vault)
                    dialog.pass_input.setText(PASSWORD)
                    dialog.unlock_btn.click()
                    if dialog.result() != QDialog.DialogCode.Accepted:
                        dialog.reject()
                QTimer.singleShot(0, action)
                return QDialog.exec(dialog)
            check(vault.exists() == (stage == "reopen"), "Vault presence matches clean/create or restart stage")
            # Unexpected return to selector cancels instead of looping indefinitely.
            selections = [True]
            def select_once(dialog):
                if selections:
                    selections.pop()
                    return select(dialog)
                return QDialog.DialogCode.Rejected
            with patch.object(module.VaultSelectorDialog, "exec", select_once), \
                 patch.object(module.VaultCreateDialog, "exec", create), \
                 patch.object(module.VaultUnlockDialog, "exec", unlock):
                cockpit.unlock_button.click()
            _application.processEvents()
            check(cockpit.stack.currentIndex() == 1, "Real cockpit unlock signal reaches unlocked screen")
            from matrix_gui.core.dialog.terminal_mode_dialog import TerminalModeDialog
            terminal = TerminalModeDialog(cockpit)
            terminal.show()
            _application.processEvents()
            check(terminal.controls.isVisible(), "Terminal Mode opens its own authoring window after unlock")
            terminal.reject()
            terminal.deleteLater()
            check(isinstance(module.VaultService.load_vault(str(vault), PASSWORD), dict), "Vault independently decrypts after cockpit route")
            from matrix_gui.swarm_workspace.workspace_manager import WorkspaceManagerDialog
            from matrix_gui.swarm_workspace.swarm_workspace import SwarmWorkspaceDialog
            core = module.VaultCoreSingleton.get()
            if stage == "create":
                manager = WorkspaceManagerDialog()
                opened = []
                manager.workspace_selected.connect(opened.append)
                manager.new_btn.click()
                check(len(opened) == 1, "New workspace control creates one workspace after fresh cockpit unlock")
                if not opened:
                    raise ScenarioFailure(checks, failures + ["No workspace to open"])
                uid = opened[0]
                manager.deleteLater()
            else:
                matches = [uid for uid, record in core.read()["workspaces"].items()
                           if record.get("label") == "COLD START WORKSPACE"]
                check(len(matches) == 1, "Workspace persisted across complete cockpit process restart")
                if not matches:
                    raise ScenarioFailure(checks, failures + ["Saved workspace missing"])
                uid = matches[0]
            graph = SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=core.read()["workspaces"][uid])
            check(bool(graph.controller.nodes), "Workspace graph loads after full cockpit unlock")
            graph.workspace_data["label"] = "COLD START WORKSPACE"
            check(graph.save(), "Workspace save request accepted")
            deadline = time.monotonic() + 15
            while graph._saving and time.monotonic() < deadline:
                _application.processEvents()
                time.sleep(0.005)
            check(not graph._saving and graph._saved_entry is not None, "Workspace background write completes")
            check(module.VaultService.load_vault(str(vault), PASSWORD)["workspaces"][uid]["label"] == "COLD START WORKSPACE",
                  "Saved workspace verified from encrypted disk, not UI cache")
            graph.close()
            check(not critical.called and not warning.called, "No error/warning dialogs during cold start")
            original_bytes = vault.read_bytes()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                 patch.object(module.VaultSelectorDialog, "exec", return_value=QDialog.DialogCode.Rejected):
                cockpit.control_panel.reopen_vault()
            check(cockpit.stack.currentIndex() == 0 and not cockpit.control_panel.isEnabled() and core._closed,
                  "Close vault then Cancel locks full cockpit and closes old core")
            check(vault.read_bytes() == original_bytes, "Close/Cancel preserves encrypted vault bytes")
            def select_unlock(dialog):
                QTimer.singleShot(0, dialog.unlock_btn.click)
                return QDialog.exec(dialog)
            critical.reset_mock()
            warning.reset_mock()
            with patch.object(module.VaultSelectorDialog, "exec", select_unlock), \
                 patch.object(module.VaultUnlockDialog, "exec", unlock), \
                 patch.object(module.VaultService, "initialize_runtime", side_effect=RuntimeError("TEST-PRIVATE-PAYLOAD")), \
                 patch.object(module, "emit_gui_exception_log") as logged:
                cockpit.unlock_button.click()
                check(logged.called and (critical.called or warning.called), "Runtime initialization failure is logged AND visible to user")
                check("TEST-PRIVATE-PAYLOAD" not in str(critical.call_args), "Failure dialog does not expose raw exception payload")
            check(cockpit.stack.currentIndex() == 0 and vault.read_bytes() == original_bytes,
                  "Runtime failure leaves cockpit locked and disk unchanged")
            with patch.object(module.VaultSelectorDialog, "exec", select_unlock), patch.object(module.VaultUnlockDialog, "exec", unlock):
                cockpit.unlock_button.click()
            check(cockpit.stack.currentIndex() == 1 and cockpit.control_panel.isEnabled(),
                  "Retry after runtime failure reopens functioning cockpit")
            from matrix_gui.modules.vault.services import vault_service_loader
            from PyQt6.QtGui import QCloseEvent
            active_core = module.VaultCoreSingleton.get()
            real_write = vault_service_loader.save_vault_singlefile
            entered, release = threading.Event(), threading.Event()
            def held_write(*args):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("Test release deadline")
                return real_write(*args)
            outcomes = []
            with patch.object(vault_service_loader, "save_vault_singlefile", side_effect=held_write):
                try:
                    active_core.save_workspace_async(active_core.read()["workspaces"][uid], outcomes.append)
                    check(entered.wait(3), "Background writer reached shutdown test barrier")
                    closing = QCloseEvent()
                    cockpit.closeEvent(closing)
                    check(not closing.isAccepted(), "Cockpit close is deferred while background vault write is active")
                    check(cockpit.pipe_timer.isActive(), "Deferred shutdown leaves cockpit monitoring intact")
                finally:
                    release.set()
                deadline = time.monotonic() + 15
                while active_core._workspace_active is not None and time.monotonic() < deadline:
                    _application.processEvents()
                    time.sleep(0.005)
            check(outcomes == [True], "Held encrypted write finishes after deferred close")
            unsaved = SwarmWorkspaceDialog(root / "phoenix/agents_meta", workspace_data=active_core.read()["workspaces"][uid])
            unsaved.show()
            unsaved.workspace_data["label"] = "UNSAVED SHUTDOWN TEST"
            closing = QCloseEvent()
            cockpit.closeEvent(closing)
            check(not closing.isAccepted() and cockpit.pipe_timer.isActive(), "Unsaved visible workspace prevents cockpit teardown")
            unsaved.workspace_data["label"] = "COLD START WORKSPACE"
            unsaved.close()
            deadline = time.monotonic() + 15
            while unsaved._saving and time.monotonic() < deadline:
                _application.processEvents()
                time.sleep(0.005)
            from PyQt6.QtCore import QThread
            release_worker = threading.Event()
            class HeldWorker(QThread):
                def run(self):
                    release_worker.wait(10)
            worker_dialog = QDialog(cockpit)
            worker = HeldWorker(worker_dialog)
            worker.start()
            try:
                closing = QCloseEvent()
                cockpit.closeEvent(closing)
                check(not closing.isAccepted(), "Running Qt child worker prevents ordinary cockpit shutdown")
            finally:
                release_worker.set()
                check(worker.wait(3000), "Test worker finishes cleanly before Qt destruction")
            worker_dialog.deleteLater()
            cockpit.close()
            check(not cockpit.isVisible(), "Cockpit closes successfully after saves and workspace resolution")
    finally:
        builtins.print = original_print
    if failures:
        raise ScenarioFailure(checks, failures)
    return checks
