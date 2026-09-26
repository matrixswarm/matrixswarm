"""Exercise registry CRUD via actual buttons/modal editors and encrypted persistence."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from .vault_scenario import PASSWORD


class ScenarioFailure(AssertionError):
    def __init__(self, checks, failures):
        self.checks = checks
        self.failures = failures
        super().__init__("; ".join(failures))


def run(stage, sandbox):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox
    from matrix_gui.core.event_bus import EventBus
    from matrix_gui.modules.vault.vault_service import VaultService
    from matrix_gui.modules.vault.services import vault_service_loader
    from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
    from matrix_gui.registry import registry_manager
    from matrix_gui.registry.object_classes.editors.ssh import SSH

    app = QApplication.instance() or QApplication([])
    vault = Path(sandbox) / "test-vault.json"
    expected_file = Path(sandbox) / "expected-registry.json"
    checks, failures = [], []
    pin = "SHA256:" + "A" * 43

    def check(condition, label):
        (checks if condition else failures).append(label)

    def disk():
        return VaultService.load_vault(str(vault), PASSWORD)

    def initialize():
        EventBus.clear()
        vault_service_loader.initialize()
        VaultService.initialize_runtime(disk(), PASSWORD, str(vault))
        return registry_manager.RegistryManagerDialog(class_lock="ssh")

    def fill(editor):
        editor.label.setText("LAB SSH PROFILE")
        editor.host.setText("server.example.invalid")
        editor.port.setText("22")
        editor.username.setText("lab-user")
        editor.auth_type.setCurrentText("password")
        editor.password.setText("LAB-ONLY-SYNTHETIC-SSH-PASSWORD")
        editor.fingerprint.setText(pin)

    def edit_through_modal(button, configure, cancel=False):
        original_exec = QDialog.exec
        observed = {}
        def drive(dialog):
            editor = dialog.findChild(SSH)
            if editor is None:
                raise AssertionError("Expected actual SSH editor inside BaseEditor modal")
            def click():
                try:
                    configure(editor)
                    buttons = dialog.findChild(QDialogButtonBox)
                    buttons.button(QDialogButtonBox.StandardButton.Cancel if cancel else QDialogButtonBox.StandardButton.Ok).click()
                    observed["accepted"] = dialog.result() == QDialog.DialogCode.Accepted
                    if not observed["accepted"]:
                        dialog.reject()
                except Exception as exc:
                    observed["error"] = str(exc)
                    dialog.reject()
            QTimer.singleShot(0, click)
            return original_exec(dialog)
        with patch.object(QDialog, "exec", drive):
            button.click()
        if "error" in observed:
            raise AssertionError(observed["error"])
        return observed.get("accepted", False)

    with patch.object(QMessageBox, "warning") as warning, patch.object(QMessageBox, "critical"), patch.object(QMessageBox, "information"), \
         patch.object(registry_manager, "emit_gui_exception_log") as error_log:
        manager = initialize()
        core = VaultCoreSingleton.get()
        if stage == "save":
            before = deepcopy(core.read())
            ciphertext = vault.read_bytes()
            check(not edit_through_modal(manager.add_btn, fill, cancel=True), "Canceled Add editor is rejected")
            check(core.read() == before and vault.read_bytes() == ciphertext, "Canceled Add changes neither runtime data nor encrypted file")
            check(edit_through_modal(manager.add_btn, fill), "Valid profile accepted through actual OK button")
            records = disk()["registry"]["ssh"]
            check(len(records) == 1, "Exactly one profile persisted")
            serial, profile = next(iter(records.items()))
            check(len(serial) == 32 and profile["serial"] == serial, "Stable serial stored as key and profile identity")
            check(profile["path"] == ["config", "ssh"] and profile["class"] == "ssh", "Registry path and class persisted")
            check(profile["meta"]["version"] == 1 and bool(profile["meta"]["created"]), "Creation metadata stored")
            check(profile["host"] == "server.example.invalid" and profile["trusted_host_fingerprint"] == pin, "Synthetic target and trust pin persisted")
            check(b"LAB-ONLY-SYNTHETIC-SSH-PASSWORD" not in vault.read_bytes(), "SSH password absent from plaintext vault file")
            check(core.read()["registry"]["ssh"] == records, "Runtime and encrypted disk profile agree")
            expected_file.write_text(json.dumps(records), encoding="utf-8")
        elif stage == "edit":
            expected = json.loads(expected_file.read_text(encoding="utf-8"))
            check(core.read()["registry"]["ssh"] == expected, "Created profile recovered after interpreter restart")
            serial = next(iter(expected))
            manager.tabs.currentWidget().setCurrentRow(1)
            check(manager._current_selection() == ("ssh", serial), "Reloaded list selects original identity")
            before, ciphertext = deepcopy(core.read()), vault.read_bytes()
            check(not edit_through_modal(manager.edit_btn, lambda e: e.label.setText("CANCELED EDIT"), cancel=True), "Canceled Edit is rejected")
            check(core.read() == before and vault.read_bytes() == ciphertext, "Canceled Edit leaves runtime and disk unchanged")
            def update(editor):
                check(editor.get_serial() == serial and editor.host.text() == expected[serial]["host"], "Editor loaded actual saved profile")
                editor.label.setText("LAB EDITED PROFILE")
                editor.port.setText("2222")
                editor.username.setText("lab-edited-user")
            check(edit_through_modal(manager.edit_btn, update), "Edited profile accepted via actual OK button")
            records = disk()["registry"]["ssh"]
            check(list(records) == [serial] and records[serial]["port"] == 2222, "Edit preserves identity and saves changed values")
            check(records[serial]["meta"]["created"] == expected[serial]["meta"]["created"], "Edit retains original creation timestamp")
            check(core.read()["registry"]["ssh"] == records, "Edited runtime and disk agree")
            expected_file.write_text(json.dumps(records), encoding="utf-8")
        elif stage == "reopen":
            expected = json.loads(expected_file.read_text(encoding="utf-8"))
            check(core.read()["registry"]["ssh"] == expected, "Edited record survives another process restart")
            from matrix_gui.modules.railgun.ssh_support import load_registry_ssh_profiles
            profiles = load_registry_ssh_profiles()
            serial = next(iter(expected))
            check(serial in profiles and profiles[serial]["port"] == 2222, "Downstream SSH profile loader sees persisted edit")
            check(profiles[serial]["username"] == "lab-edited-user", "Downstream loader sees edited account")
            editor = SSH(new_conn=False)
            editor._load_data(expected[serial])
            check(editor.is_validated()[0], "Reloaded saved profile still validates")
            check(editor.password.text() == "LAB-ONLY-SYNTHETIC-SSH-PASSWORD", "Encrypted credential survives full round trip")
        elif stage == "validation":
            for label, field, value in (
                ("missing label", "label", ""), ("missing host", "host", ""),
                ("missing username", "username", ""), ("nonnumeric port", "port", "oops"),
                ("zero port", "port", "0"), ("out-of-range port", "port", "65536"),
                ("missing password", "password", ""), ("missing host pin", "fingerprint", ""),
                ("malformed host pin", "fingerprint", "not-a-sha256-pin"),
            ):
                manager = initialize()
                before = deepcopy(VaultCoreSingleton.get().read())
                ciphertext = vault.read_bytes()
                def invalid(editor):
                    fill(editor)
                    getattr(editor, field).setText(value)
                accepted = edit_through_modal(manager.add_btn, invalid)
                check(not accepted, f"Invalid input must be rejected: {label}")
                check(VaultCoreSingleton.get().read() == before and vault.read_bytes() == ciphertext, f"Invalid input must not mutate runtime/disk: {label}")
            for port in ("1", "65535"):
                for fingerprint in (pin, pin + "="):
                    editor = SSH(new_conn=True)
                    fill(editor)
                    editor.port.setText(port)
                    editor.fingerprint.setText(fingerprint)
                    check(editor.is_validated()[0], f"Valid port boundary {port} and fingerprint padding remain supported: {fingerprint.endswith('=')}")
            for fingerprint in ("SHA256:" + "B" * 43, "SHA256:" + "A" * 42, pin + "=="):
                editor = SSH(new_conn=True)
                fill(editor)
                editor.fingerprint.setText(fingerprint)
                check(not editor.is_validated()[0], "Noncanonical digest/length/padding rejected")
        elif stage == "commit-failure":
            for operation, raises in ((op, mode) for op in ("add", "edit", "delete") for mode in (False, True)):
                manager = initialize()
                core = VaultCoreSingleton.get()
                before, ciphertext = deepcopy(core.read()), vault.read_bytes()
                manager.tabs.currentWidget().setCurrentRow(1)
                warning.reset_mock()
                with patch.object(manager.registry_store, "commit", return_value=False, side_effect=RuntimeError("synthetic commit failure") if raises else None):
                    if operation == "add":
                        edit_through_modal(manager.add_btn, fill)
                    elif operation == "edit":
                        edit_through_modal(manager.edit_btn, lambda e: e.label.setText("REJECTED COMMIT"))
                    else:
                        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                            manager.del_btn.click()
                check(vault.read_bytes() == ciphertext, f"Rejected {operation} commit leaves disk unchanged")
                check(core.read() == before, f"Rejected {operation} commit must roll back runtime mutation")
                check(warning.called and warning.call_args.args[1] == "Registry Save Failed", f"Rejected {operation} commit reports failure to operator")
        else:
            raise ValueError("Unknown registry scenario")
        check(not error_log.called, "No unexpected registry handler exceptions")
    app.processEvents()
    if failures:
        raise ScenarioFailure(checks, failures)
    return checks
