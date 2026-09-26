# Authored by Daniel F MacDonald & ChatGPT-5 aka The Generals
from PyQt6 import QtWidgets, QtCore
from matrix_gui.modules.railgun.request_identity import request_identity
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.util.exception_diagnostics import log_exception_locations
from matrix_gui.modules.railgun.control_worker import ControlSessionWorker
from matrix_gui.modules.railgun.ssh_support import (
    format_ssh_profile_label,
)
from matrix_gui.modules.railgun.remote_shell import (
    build_remote_matrixd_command,
    default_linux_user,
    describe_runtime_capabilities,
    derive_runtime_capabilities,
    mcp_worker_linux_user,
    validate_linux_user,
    validate_remote_token,
)
QtCore.QCoreApplication.processEvents()
class DeployDialog(QtWidgets.QDialog):
    """Railgun-style MatrixD controller over SSH, with SSH selector."""

    def __init__(self, ssh_map, default_serial=None, deployment=None, parent=None):
        super().__init__(parent)

        self.setWindowTitle("MatrixD Control")
        self.resize(700, 520)

        self.ssh_map = ssh_map
        self.deployment = deployment or {}
        self._ssh_client = None
        self._active_channel = None
        self._poll_timer = None
        self._prepare_worker = None
        self.layout = QtWidgets.QVBoxLayout(self)

        # -------------------------------
        # SSH Dropdown Row
        # -------------------------------
        ssh_row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel("SSH Target:")
        ssh_row.addWidget(label)

        self.ssh_selector = QtWidgets.QComboBox()
        for sid, meta in ssh_map.items():
            display = format_ssh_profile_label(sid, meta)
            self.ssh_selector.addItem(display, meta)

            # auto-select based on stored serial
            if default_serial and sid == default_serial:
                self.ssh_selector.setCurrentIndex(self.ssh_selector.count() - 1)

        ssh_row.addWidget(self.ssh_selector)
        self.layout.addLayout(ssh_row)

        # -------------------------------
        # Start / Restart Options
        # -------------------------------
        opts_group = QtWidgets.QGroupBox("Start / Restart Options")
        opts_layout = QtWidgets.QVBoxLayout()

        # Universe selection
        self.universe_edit = QtWidgets.QLineEdit()
        self.universe_edit.setPlaceholderText("Universe name (default: deployment label)")
        if self.deployment:
            self.universe_edit.setText(
                self.deployment.get("universe")
                or self.deployment.get("label", "")
            )

        opts_layout.addWidget(QtWidgets.QLabel("Universe:"))
        opts_layout.addWidget(self.universe_edit)

        self.linux_user_edit = QtWidgets.QLineEdit()
        configured_linux_user = self.deployment.get("linux_user")
        if not configured_linux_user:
            try:
                configured_linux_user = default_linux_user(
                    self.deployment.get("label", "phoenix")
                )
            except ValueError:
                configured_linux_user = "matrix-phoenix"
        self.linux_user_edit.setText(configured_linux_user)
        self.linux_user_edit.setPlaceholderText("matrix-phoenix")
        self.linux_user_edit.setToolTip(
            "Least-privilege Linux account used to run Matrix and this universe."
        )
        opts_layout.addWidget(QtWidgets.QLabel("Swarm Linux User:"))
        opts_layout.addWidget(self.linux_user_edit)

        sealed_status = QtWidgets.QLabel(
            "Sealed directive: retained inside the encrypted Phoenix vault; "
            "streamed to MatrixD only for Start/Restart."
        )
        sealed_status.setWordWrap(True)
        opts_layout.addWidget(sealed_status)

        # Flags
        self.flag_verbose = QtWidgets.QCheckBox("--verbose")
        self.flag_verbose.setEnabled(False)
        self.flag_verbose.setToolTip(
            "Disabled for SSH boots: detached agents must not inherit the SSH output channel. "
            "Use the cockpit agent logs for live output."
        )
        self.flag_debug = QtWidgets.QCheckBox("--debug")
        self.flag_clean = QtWidgets.QCheckBox("--clean")
        self.flag_rugpull = QtWidgets.QCheckBox("--rug-pull")
        self.flag_reboot_new = QtWidgets.QCheckBox("--reboot-new")
        self.flag_protect_memory = QtWidgets.QCheckBox("--protect-memory")
        self.flag_protect_memory.setChecked(
            bool(self.deployment.get("protect_memory", True))
        )
        self.flag_protect_memory.setToolTip(
            "Restrict agent memory and environment inspection to root or "
            "CAP_SYS_PTRACE."
        )

        flag_row = QtWidgets.QHBoxLayout()
        for f in (self.flag_verbose, self.flag_debug, self.flag_clean,
                  self.flag_rugpull, self.flag_reboot_new,
                  self.flag_protect_memory):
            flag_row.addWidget(f)

        opts_layout.addWidget(QtWidgets.QLabel("Boot Flags:"))
        opts_layout.addLayout(flag_row)
        self.new_boot_operation = QtWidgets.QCheckBox("New intentional boot/restart (not a retry)")
        self.new_boot_operation.setToolTip(
            "Leave unchecked after connection loss to reuse the saved request. "
            "Check only when deliberately starting another boot after inspecting the target."
        )
        opts_layout.addWidget(self.new_boot_operation)

        opts_group.setLayout(opts_layout)
        self.layout.addWidget(opts_group)


        # -------------------------------
        # Output Console
        # -------------------------------
        self.output = QtWidgets.QTextEdit(readOnly=True)
        self.output.setStyleSheet(
            "background:#000;color:#00ff00;font-family:Consolas,monospace;font-size:12px;"
        )
        self.layout.addWidget(self.output)
        self.operation_status = QtWidgets.QLabel("Ready")
        self.layout.addWidget(self.operation_status)
        self.cancel_operation = QtWidgets.QPushButton("Cancel local operation")
        self.cancel_operation.setEnabled(False)
        self.cancel_operation.clicked.connect(self._cancel_operation)
        self.layout.addWidget(self.cancel_operation)

        # -------------------------------
        # Action Buttons
        # -------------------------------
        btns = QtWidgets.QHBoxLayout()

        for label, cmd in (
            ("Start", "start"),
            ("Stop", "stop"),
            ("Restart", "restart"),
        ):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _, c=cmd: self._run_remote(c))
            btns.addWidget(b)

        retry = QtWidgets.QPushButton("Retry initial Railgun request")
        retry.setEnabled(bool(self.deployment.get("railgun_boot_options")))
        retry.setToolTip("Reuse the original saved request and options after a lost acknowledgement; never create a new boot identity.")
        retry.clicked.connect(self._retry_initial_request)
        btns.addWidget(retry)

        btns.addStretch(1)

        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        btns.addWidget(close)

        self.layout.addLayout(btns)

    # ----------------------------------------------------
    def _retry_initial_request(self):
        try:
            self._launch_initial_retry()
        except Exception as error:
            log_exception_locations("Railgun initial retry", error)
            self.output.append(
                f"[ERROR] Initial retry could not be opened ({type(error).__name__}). "
                "Inspect the saved deployment and diagnostic log. "
                "Do not assume the remote outcome or create a new boot blindly."
            )

    def _launch_initial_retry(self):
        if self._active_channel is not None or self._prepare_worker is not None:
            self.output.append("[BLOCKED] Another operation is active.")
            return
        target = self.ssh_selector.currentData()
        if not isinstance(target, dict):
            return
        actual = {"host": str(target.get("host", "")).strip().lower(),
                  "port": int(target.get("port", 22)),
                  "pin": target.get("trusted_host_fingerprint", "")}
        if actual != self.deployment.get("railgun_target_identity"):
            self.output.append("[BLOCKED] Original retry requires the same host, port and pinned host key.")
            return
        opts = self.deployment.get("railgun_boot_options")
        if not isinstance(opts, dict) or not opts.get("railgun_request_id"):
            self.output.append("[BLOCKED] This deployment has no durable initial request identity.")
            return
        from matrix_gui.swarm_workspace.cls_lib.deployment.dialog.railgun import RailgunDialog
        RailgunDialog.launch(self, target, self.deployment["encrypted_bundle"],
                             self.deployment["swarm_key"], dict(opts))

    def _run_remote(self, action: str):
        try:
            self._prepare_remote(action)
        except Exception as error:
            log_exception_locations("MatrixD control validation", error)
            self.output.append(f"[ERROR] Could not prepare operation ({type(error).__name__}); inspect deployment settings.")

    def _prepare_remote(self, action):
        if self._active_channel is not None or self._prepare_worker is not None:
            self.output.append("[BLOCKED] Wait for the active operation before another request.")
            return
        ssh_cfg = self.ssh_selector.currentData()
        if not isinstance(ssh_cfg, dict):
            self.output.append("[ERROR] Select a vault-backed SSH target.\n")
            return

        # SSH data (registry)
        host = ssh_cfg["host"]
        user = ssh_cfg["username"]
        port = int(ssh_cfg.get("port", 22))
        auth_type = ssh_cfg.get("auth_type", "private_key")
        privkey_pem = ssh_cfg.get("private_key")

        if auth_type == "private_key" and not privkey_pem:
            self.output.append("[ERROR] No private key provided.\n")
            return

        # Deployment data (runtime)
        swarm_key = self.deployment.get("swarm_key")
        encrypted_bundle = self.deployment.get("encrypted_bundle")
        try:
            universe = validate_remote_token(
                self.universe_edit.text().strip() or self.deployment["label"],
                "Universe name",
            )
        except ValueError as error:
            self.output.append(f"[ERROR] {error}\n")
            return

        flags = []
        if self.flag_debug.isChecked(): flags.append("--debug")
        if self.flag_clean.isChecked(): flags.append("--clean")
        if self.flag_rugpull.isChecked(): flags.append("--rug-pull")
        if self.flag_reboot_new.isChecked(): flags.append("--reboot-new")
        if self.flag_protect_memory.isChecked(): flags.append("--protect-memory")
        try:
            linux_user = validate_linux_user(
                self.linux_user_edit.text(), "Swarm Linux user"
            )
        except ValueError as error:
            self.output.append(f"[ERROR] {error}\n")
            return

        self.output.append(f"[SSH] Connecting to {host} as {user} via {auth_type}\n")

        try:

            if action != "stop" and (
                not swarm_key or not isinstance(encrypted_bundle, dict)
            ):
                self.output.append(
                    "[ERROR] This deployment predates sealed-stream Railgun. "
                    "Redeploy it from Phoenix before Start/Restart.\n"
                )
                return

            universe = validate_remote_token(universe, "Universe name")

            stored_agents = self.deployment.get("agents", {})
            runtime_capabilities = (
                derive_runtime_capabilities(stored_agents)
                if stored_agents
                else self.deployment.get("runtime_capabilities") or {}
            )
            request_id = None
            if action != "stop":
                intentional_new = self.new_boot_operation.isChecked()
                if intentional_new and QtWidgets.QMessageBox.question(
                    self, "New Remote Operation",
                    "This intentionally permits another boot/restart. If a previous "
                    "outcome is unknown, inspect the target first. Continue?",
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No,
                ) != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
                request_id = request_identity(VaultCoreSingleton.get(), ssh_cfg,
                    {"action": action, "universe": universe, "linux_user": linux_user,
                     "flags": flags, "capabilities": runtime_capabilities,
                     "bundle": encrypted_bundle}, new_operation=intentional_new)
                self.new_boot_operation.setChecked(False)
            cmd = build_remote_matrixd_command(
                action=action,
                universe=universe,
                linux_user=linux_user,
                boot_flags=flags,
                runtime_capabilities=runtime_capabilities,
                request_id=request_id,
            )
            self.output.append(f"[ACCOUNT] Universe runs as {linux_user}\n")
            grants = describe_runtime_capabilities(runtime_capabilities)
            self.output.append(
                f"[ACCOUNT] Railgun-managed active grants: {len(grants)}\n"
            )
            for grant in grants:
                self.output.append(f"[ACCOUNT]   {grant}\n")
            if not grants:
                self.output.append(
                    "[ACCOUNT]   none — unprivileged universe account\n"
                )
            if runtime_capabilities.get("mcp_worker"):
                self.output.append(
                    "[ACCOUNT] MCP worker runs as "
                    f"{mcp_worker_linux_user(linux_user)} (isolated)\n"
                )
            self.output.append(
                "[CMD] Root provisioning and least-privilege MatrixD launch prepared; "
                "no directive or key is present in the command.\n"
            )

            worker = ControlSessionWorker(ssh_cfg, cmd, action, encrypted_bundle, swarm_key, self)
            self._prepare_worker = worker
            worker.status.connect(self._preparation_status)
            worker.finished.connect(self._preparation_finished)
            self.operation_status.setText("Preparing SSH session…")
            self.cancel_operation.setEnabled(True)
            try:
                worker.start()
            except Exception:
                self._prepare_worker = None
                self.cancel_operation.setEnabled(False)
                self.operation_status.setText("Worker could not start")
                worker.deleteLater()
                raise

        except Exception as e:
            log_exception_locations("MatrixD control setup", e)
            self.output.append(f"[ERROR] Setup failed ({type(e).__name__}).")

    @QtCore.pyqtSlot(str)
    def _preparation_status(self, message):
        if self._prepare_worker and not self._prepare_worker.cancelled.is_set():
            self.operation_status.setText(message)

    @QtCore.pyqtSlot()
    def _preparation_finished(self):
        worker = self._prepare_worker
        if worker is None:
            return
        self._prepare_worker = None
        if worker.result is not None:
            self._ssh_client, self._active_channel = worker.result
            worker.result = None
            if worker.cancelled.is_set():
                self.output.append("[UNKNOWN] Local operation cancelled; remote outcome is unknown.")
                self._close_ssh_session()
            else:
                if self._poll_timer is None:
                    self._poll_timer = QtCore.QTimer(self)
                    self._poll_timer.timeout.connect(self._poll_ssh_channel)
                self._poll_timer.start(120)
                self.operation_status.setText("Reading remote output…")
        else:
            self.output.append(worker.error or "[ERROR] Preparation ended without a session.")
            self.operation_status.setText("Stopped — inspect output; Close is available")
            self.cancel_operation.setEnabled(False)
        worker.deleteLater()

    def _cancel_operation(self):
        if self._prepare_worker is not None:
            self._prepare_worker.cancel()
            self.operation_status.setText("Cancelling — waiting for bounded SSH step; close again when clear")
        elif self._active_channel is not None:
            self.output.append("[UNKNOWN] Local connection cancelled; remote work may continue. Inspect target before a new operation.")
            self._close_ssh_session()

    def _defer_close(self):
        if self._prepare_worker is None:
            return False
        self._cancel_operation()
        return True

    def _poll_ssh_channel(self):
        chan = getattr(self, "_active_channel", None)
        if chan is None:
            if self._poll_timer is not None:
                self._poll_timer.stop()
            return

        try:
            # Bound each GUI turn, with equal budgets so stderr cannot starve.
            # Keep polling after exit until both buffers have been drained.
            for ready, receive in ((chan.recv_ready, chan.recv),
                                   (chan.recv_stderr_ready, chan.recv_stderr)):
                for _ in range(16):
                    if not ready():
                        break
                    data = receive(4096)
                    if not data:
                        break
                    cursor = self.output.textCursor()
                    cursor.movePosition(cursor.MoveOperation.End)
                    cursor.insertText(data.decode(errors="replace"))

            # Finished?
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                code = chan.recv_exit_status()
                if code < 0:
                    self.output.append("[UNKNOWN] SSH ended without an exit status. Retry with the same options/request; do not select a new operation blindly.")
                else:
                    self.output.append(f"\n[Exit {code}] remote command ended; inspect output for receipt/replay or blocked status.\n")
                self._close_ssh_session()

        except Exception as e:
            log_exception_locations("MatrixD control stream", e)
            self.output.append(f"[UNKNOWN] SSH stream failed ({type(e).__name__}); remote outcome is unknown. Inspect the target before any new operation.")
            self._close_ssh_session()

    def _close_ssh_session(self):
        self.operation_status.setText("Ready — inspect output for remote outcome")
        self.cancel_operation.setEnabled(False)
        if self._poll_timer is not None:
            self._poll_timer.stop()

        chan = self._active_channel
        self._active_channel = None
        if chan is not None:
            try:
                chan.close()
            except Exception as error:
                log_exception_locations("MatrixD control channel cleanup", error)

        client = self._ssh_client
        self._ssh_client = None
        if client is not None:
            try:
                client.close()
            except Exception as error:
                log_exception_locations("MatrixD control client cleanup", error)

    def done(self, result):
        if self._defer_close():
            return
        self._close_ssh_session()
        super().done(result)

    def reject(self):
        if self._defer_close():
            return
        self._close_ssh_session()
        super().reject()

    def closeEvent(self, event):
        if self._defer_close():
            event.ignore()
            return
        self._close_ssh_session()
        super().closeEvent(event)
