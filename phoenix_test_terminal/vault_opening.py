"""Real unlock dialogs and cockpit routing; only hardware and modal input are faked."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from .vault_scenario import PASSWORD, ROTATED


def run(stage, sandbox):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QWidget
    from matrix_gui.modules.vault import vault_unlock_dialog as unlock_module
    from matrix_gui.modules.vault import yubikey_worker
    from matrix_gui.modules.vault.vault_create_dialog import VaultCreateDialog
    from matrix_gui.modules.vault.vault_selector_dialog import VaultSelectorDialog
    from matrix_gui.modules.vault.vault_change_password_dialog import VaultChangePasswordDialog
    from matrix_gui.modules.vault.vault_service import VaultService
    from matrix_gui.core.event_bus import EventBus
    from matrix_gui.core import startup_policy as policy
    from matrix_gui.modules.vault.services import vault_service_loader
    from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton

    app = QApplication.instance() or QApplication([])
    Unlock = unlock_module.VaultUnlockDialog
    vault = Path(sandbox) / "test-vault.json"
    original = vault.read_bytes()
    checks = []

    def check(condition, message):
        if not condition:
            raise AssertionError(message)
        checks.append(message)

    def selected(path=vault):
        dialog = Unlock()
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "")):
            dialog.select_btn.click()
        return dialog

    def closed(dialog):
        return dialog.result() != QDialog.DialogCode.Accepted and dialog.vault_data is None and dialog.vault_password is None

    with patch.object(QMessageBox, "warning") as warning, patch.object(QMessageBox, "critical"), patch.object(QMessageBox, "information"):
        if stage == "opening":
            dialog = Unlock()
            check(not dialog.allow_secret_viewing and not dialog.debug_output and not dialog.close_on_minimize_or_sleep, "All three session permissions default off")
            dialog.unlock_btn.click()
            check(closed(dialog) and warning.call_args.args[1] == "Missing File", "Unlock without file rejected with correct diagnostic")
            with patch.object(QFileDialog, "getOpenFileName", return_value=("", "")):
                dialog.select_btn.click()
            check(dialog.vault_path is None and closed(dialog), "Cancel file picker leaves vault unopened")
            dialog = selected()
            check(dialog.vault_path == str(vault) and str(vault) in dialog.selected_file_label.text(), "Selected file path and visible label agree")
            with patch.object(QFileDialog, "getOpenFileName", return_value=("", "")):
                dialog.select_btn.click()
            check(dialog.vault_path == str(vault), "Cancel replacement picker preserves previous selection")
            for password in ("", "   "):
                dialog.pass_input.setText(password)
                dialog.unlock_btn.click()
                check(closed(dialog) and warning.call_args.args[1] == "Missing Password", "Empty/whitespace password rejected")
            dialog.pass_input.setText("wrong-test-password")
            dialog.unlock_btn.click()
            check(closed(dialog) and warning.call_args.args[1] == "Invalid Credential", "Wrong credential rejected without publishing data")
            dialog.pass_input.setText(PASSWORD)
            dialog.unlock_btn.click()
            check(dialog.result() == QDialog.DialogCode.Accepted and isinstance(dialog.vault_data, dict), "Wrong-password retry successfully unlocks same dialog")
            check(dialog.vault_auth_method == "password", "Password authentication metadata preserved")
            dialog = selected()
            dialog.pass_input.setText(PASSWORD)
            dialog.cancel_btn.click()
            check(closed(dialog), "Cancel unlock does not decrypt or accept")
            for name, contents in (("malformed.json", b"not json"), ("empty.json", b""), ("missing-fields.json", b"{}"), ("tampered.json", original.replace(b'"vault": "', b'"vault": "invalid', 1))):
                path = Path(sandbox) / name
                path.write_bytes(contents)
                dialog = selected(path)
                dialog.pass_input.setText(PASSWORD)
                dialog.unlock_btn.click()
                check(closed(dialog), f"Unreadable/corrupt vault rejected: {name}")
                check(path.read_bytes() == contents, f"Rejected file left unchanged: {name}")
            dialog = selected(Path(sandbox) / "does-not-exist.json")
            dialog.pass_input.setText(PASSWORD)
            dialog.unlock_btn.click()
            check(closed(dialog), "Missing file rejected")
            dialog = selected()
            dialog.pass_input.setText(PASSWORD)
            with patch.object(VaultService, "load_vault", side_effect=PermissionError("synthetic inaccessible file")):
                dialog.unlock_btn.click()
            check(closed(dialog), "File access exception rejected")
            for attribute in ("allow_secret_viewing", "debug_output", "close_on_minimize_or_sleep"):
                dialog = selected()
                getattr(dialog, attribute + "_checkbox").setChecked(True)
                dialog.pass_input.setText(PASSWORD)
                dialog.unlock_btn.click()
                check(dialog.result() == QDialog.DialogCode.Accepted and getattr(dialog, attribute), f"Explicit session option returned: {attribute}")
            # Actual QThread/signals, synthetic hardware response; never touch USB.
            for succeeds in (True, False):
                dialog = selected()
                dialog.pass_input.setText("synthetic-secondary-word")
                def hardware(*args, **kwargs):
                    kwargs["touch_callback"]()
                    if not succeeds:
                        raise RuntimeError("Synthetic YubiKey unavailable")
                    return SimpleNamespace(password=PASSWORD, serial="LAB-ONLY")
                with patch.object(yubikey_worker, "request_yubikey_credential", side_effect=hardware):
                    dialog.yubikey_btn.click()
                    worker = dialog._yubikey_worker
                    check(not dialog.unlock_btn.isEnabled() and not dialog.select_btn.isEnabled(), "YubiKey operation disables conflicting controls")
                    check(dialog.pass_input.text() == "", "Secondary word cleared during hardware request")
                    check(worker.wait(5000), "YubiKey test worker terminates")
                    app.processEvents()
                    check(dialog.unlock_btn.isEnabled(), "YubiKey completion restores controls")
                    check((dialog.result() == QDialog.DialogCode.Accepted and dialog.vault_auth_method == "yubikey") if succeeds else closed(dialog), "YubiKey simulated success/failure handled correctly")
            dialog = selected()
            dialog.pass_input.setText("synthetic-secondary-word")
            def wait_for_cancel(*args, **kwargs):
                kwargs["cancellation_event"].wait(5)
                return SimpleNamespace(password=PASSWORD, serial="LAB-ONLY")
            with patch.object(yubikey_worker, "request_yubikey_credential", side_effect=wait_for_cancel):
                dialog.yubikey_btn.click()
                worker = dialog._yubikey_worker
                dialog.cancel_btn.click()
                check(worker.wait(5000), "Cancel joins simulated hardware worker")
                app.processEvents()
                check(closed(dialog), "Late hardware credential cannot accept canceled dialog")
            check(vault.read_bytes() == original, "Opening tests never modify original test vault")
        elif stage == "routing":
            # Execute the exact production routing method without importing the
            # executable's unrelated top-level launch/process side effects.
            root = Path(__file__).resolve().parents[1]
            source = root / "phoenix/phoenix.py"
            tree = ast.parse(source.read_text(encoding="utf-8-sig"))
            method = next(node for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name == "PhoenixCockpit"
                          for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "unlock_vault")
            failures, events = [], []
            namespace = dict(VaultSelectorDialog=VaultSelectorDialog, VaultCreateDialog=VaultCreateDialog,
                             VaultUnlockDialog=Unlock, VaultChangePasswordDialog=VaultChangePasswordDialog,
                             VaultService=VaultService, QDialog=QDialog, QMessageBox=QMessageBox,
                             reset_startup_policy=policy.reset_startup_policy,
                             configure_startup_policy=policy.configure_startup_policy,
                             emit_gui_exception_log=lambda *args: failures.append(args))
            exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
            owner = QWidget()
            def route(choices, operations):
                EventBus.clear()
                vault_service_loader.initialize()
                EventBus.on("vault.unlocked", lambda **kw: events.append(kw))
                VaultCoreSingleton._instance = None
                policy.configure_startup_policy(allow_secret_viewing=True, debug_output=True, close_on_minimize_or_sleep=True)
                def selector_exec(dialog):
                    choice = choices.pop(0)
                    QTimer.singleShot(0, (dialog.cancel_btn if choice == "cancel" else getattr(dialog, choice + "_btn")).click)
                    return QDialog.exec(dialog)
                def operation_exec(dialog):
                    action = operations.pop(0)
                    def act():
                        action(dialog)
                        # Close unexpected validation failures; postconditions fail
                        # with evidence rather than hanging a modal indefinitely.
                        if dialog.result() != QDialog.DialogCode.Accepted:
                            dialog.reject()
                    QTimer.singleShot(0, act)
                    return QDialog.exec(dialog)
                with patch.object(VaultSelectorDialog, "exec", selector_exec), patch.object(Unlock, "exec", operation_exec), \
                     patch.object(VaultCreateDialog, "exec", operation_exec), patch.object(VaultChangePasswordDialog, "exec", operation_exec):
                    namespace["unlock_vault"](owner)
                check(not choices and not operations, "Cockpit consumed expected route/dialog sequence")
            def unlock(dialog, password=PASSWORD):
                if not dialog.vault_path:
                    dialog.select_btn.click()
                dialog.pass_input.setText(password)
                dialog.unlock_btn.click()
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(vault), "")):
                route(["cancel"], [])
                check(not events and VaultCoreSingleton._instance is None and not policy.secret_viewing_enabled(), "Cancel selector resets policy and never initializes runtime")
                route(["unlock", "cancel"], [lambda dialog: dialog.cancel_btn.click()])
                check(not events and VaultCoreSingleton._instance is None, "Canceled unlock returns to selector without publishing unlocked event")
                route(["unlock"], [unlock])
                check(len(events) == 1 and events[-1]["vault_path"] == str(vault), "Actual cockpit routing emits one real vault.unlocked event")
                check(VaultCoreSingleton.get().read()["registry"] == {}, "Actual cockpit routing initializes empty new-vault registry")
                check(not policy.debug_output_enabled() and not policy.close_on_minimize_or_sleep_enabled(), "Session policy follows unchecked dialog defaults")
                def privileged(dialog):
                    dialog.allow_secret_viewing_checkbox.setChecked(True)
                    dialog.debug_output_checkbox.setChecked(True)
                    dialog.close_on_minimize_or_sleep_checkbox.setChecked(True)
                    unlock(dialog)
                route(["unlock"], [privileged])
                check(policy.secret_viewing_enabled() and policy.debug_output_enabled() and policy.close_on_minimize_or_sleep_enabled(), "Actual route applies explicitly selected capabilities")
                event_count = len(events)
                with patch.object(VaultService, "initialize_runtime", side_effect=RuntimeError("synthetic runtime failure")):
                    route(["unlock"], [privileged])
                check(len(events) == event_count and len(failures) == 1, "Runtime failure logged without success event")
                check(not policy.secret_viewing_enabled() and not policy.debug_output_enabled() and not policy.close_on_minimize_or_sleep_enabled(), "Runtime failure revokes all selected capabilities")
            new_path = Path(sandbox) / "route-created.json"
            def create(dialog):
                dialog.password_input.setText(PASSWORD)
                dialog.create_btn.click()
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(new_path), "")):
                route(["create"], [create, unlock])
            check(events[-1]["vault_path"] == str(new_path) and isinstance(VaultService.load_vault(str(new_path), PASSWORD), dict), "Create route forces real unlock before runtime initialization")
            def change(dialog):
                dialog.select_btn.click()
                dialog.old_pw.setText(PASSWORD)
                dialog.new_pw.setText(ROTATED)
                dialog.change_btn.click()
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(new_path), "")):
                route(["change", "unlock"], [change, lambda dialog: unlock(dialog, ROTATED)])
            check(events[-1]["password"] == ROTATED and VaultService.load_vault(str(new_path), PASSWORD) is False, "Change-password route returns to selector and requires new-password unlock")
            check(len(failures) == 1 and vault.read_bytes() == original, "No unexpected routing failures; lifecycle fixture unchanged")
            policy.reset_startup_policy()
            EventBus.clear()
        else:
            raise ValueError("Unknown opening stage")
    app.processEvents()
    return checks
