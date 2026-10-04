# Authored by Daniel F MacDonald & ChatGPT-5 aka The Generals
from PyQt6 import QtWidgets, QtCore
from matrix_gui.modules.railgun.request_identity import request_scope_key
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
    """Railgun-style MatrixD controller bound to a saved deployment target."""

    def __init__(self, ssh_map, default_serial=None, deployment=None,
                 vault_connection=None, parent=None):
        super().__init__(parent)

        self.setWindowTitle("MatrixD Control")
        self.resize(700, 520)

        self.ssh_map = ssh_map
        self.deployment = deployment or {}
        self.vault_connection = vault_connection
        self._target_error = None
        self._bound_profile = None
        self._ssh_client = None
        self._active_channel = None
        self._poll_timer = None
        self._prepare_worker = None
        # Keep recovery available when the operator closes and reopens this
        # dialog in the same cockpit session. Only public request metadata is
        # cached; the live vault still validates its scope and identity.
        self._control_requests = (
            vars(vault_connection).setdefault("_matrixd_control_requests", {})
            if vault_connection is not None else {}
        )
        self._retry_control_actions = {}
        self.layout = QtWidgets.QVBoxLayout(self)

        # -------------------------------
        # SSH Dropdown Row
        # -------------------------------
        ssh_row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel("SSH Target:")
        ssh_row.addWidget(label)

        self.ssh_selector = QtWidgets.QComboBox()
        serial = self.deployment.get("ssh_serial")
        recorded = self.deployment.get("railgun_target_identity")
        # A live session must never infer a replacement profile by host match.
        candidates = [(serial, ssh_map.get(serial))] if serial else []
        matches = [(sid, meta) for sid, meta in candidates if isinstance(meta, dict)
                   and isinstance(recorded, dict) and self._target_identity(meta) == recorded]
        if len(matches) == 1:
            sid, meta = matches[0]
            self._bound_profile = dict(meta)
            self.ssh_selector.addItem(format_ssh_profile_label(sid, meta), dict(meta))
        else:
            self._target_error = "The deployment's recorded SSH target is missing or changed; reopen or redeploy it."
            self.ssh_selector.addItem("Recorded SSH target unavailable", None)
        self.ssh_selector.setEnabled(False)

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
        self.universe_edit.setReadOnly(True)

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
        self.linux_user_edit.setReadOnly(True)
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
        if self._target_error:
            self.output.append(f"[BLOCKED] {self._target_error}")
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
            if cmd == "stop":
                b = QtWidgets.QPushButton(label)
            else:
                b = QtWidgets.QToolButton()
                b.setText(label)
                b.setObjectName("MatrixDOperationButton")
                b.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.MenuButtonPopup)
                b.setToolTip(
                    f"{label} the saved deployment. Use the arrow for recovery after connection loss."
                )
                menu = QtWidgets.QMenu(b)
                retry_control = menu.addAction(f"Retry last {label.lower()}")
                retry_control.setToolTip("Use after a lost SSH reply. An already completed operation will not run again.")
                retry_control.setEnabled(cmd in self._control_requests)
                retry_control.triggered.connect(lambda _, c=cmd: self._retry_control_request(c))
                self._retry_control_actions[cmd] = retry_control
                if cmd == "start":
                    menu.addSeparator()
                    retry_initial = menu.addAction("Retry saved deployment launch")
                    options = self.deployment.get("railgun_boot_options")
                    retry_initial.setEnabled(isinstance(options, dict) and bool(options.get("railgun_request_id")))
                    retry_initial.setToolTip(
                        "Recover the original deployment request with its saved options; a completed launch is not repeated."
                    )
                    retry_initial.triggered.connect(self._retry_initial_request)
                b.setMenu(menu)
            b.setEnabled(self._target_error is None)
            b.clicked.connect(lambda _, c=cmd: self._run_remote(c))
            btns.addWidget(b)

        btns.addStretch(1)

        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        btns.addWidget(close)

        self.layout.addLayout(btns)

    # ----------------------------------------------------
    @staticmethod
    def _target_identity(target):
        try:
            return {"host": str(target.get("host", "")).strip().lower(),
                    "port": int(target.get("port", 22)),
                    "pin": target.get("trusted_host_fingerprint", "")}
        except (TypeError, ValueError):
            return None

    def _current_bound_target(self):
        selected = self.ssh_selector.currentData()
        if (self._target_error or not isinstance(selected, dict)
                or selected != self._bound_profile
                or self._target_identity(selected) != self.deployment.get("railgun_target_identity")):
            self.output.append("[BLOCKED] This session can control only its recorded SSH target.")
            return None
        return selected

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
        target = self._current_bound_target()
        if target is None:
            return
        opts = self.deployment.get("railgun_boot_options")
        if not isinstance(opts, dict) or not opts.get("railgun_request_id"):
            self.output.append("[BLOCKED] This deployment has no durable initial request identity.")
            return
        from matrix_gui.swarm_workspace.cls_lib.deployment.dialog.railgun import RailgunDialog
        RailgunDialog.launch(self, target, self.deployment["encrypted_bundle"],
                             self.deployment["swarm_key"], dict(opts))

    def _retry_control_request(self, action):
        self._run_remote(action, retry=True)

    def _run_remote(self, action: str, *, retry=False):
        try:
            self._prepare_remote(action, retry=retry)
        except Exception as error:
            log_exception_locations("MatrixD control validation", error)
            self.output.append(f"[ERROR] Could not prepare operation ({type(error).__name__}); inspect deployment settings.")

    def _prepare_remote(self, action, *, retry=False):
        if self._active_channel is not None or self._prepare_worker is not None:
            self.output.append("[BLOCKED] Wait for the active operation before another request.")
            return
        retry_request = self._control_requests.get(action) if retry else None
        if retry and retry_request is None:
            self.output.append(f"[BLOCKED] No previous {action} request is available in this window.")
            return
        ssh_cfg = self._current_bound_target()
        if ssh_cfg is None:
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
        if retry_request is not None:
            # Recovery must reproduce the saved request even if the operator
            # has since changed the visible options for their next operation.
            flags = list(retry_request["flags"])
        try:
            linux_user = validate_linux_user(
                self.linux_user_edit.text(), "Swarm Linux user"
            )
        except ValueError as error:
            self.output.append(f"[ERROR] {error}\n")
            return
        if (universe != (self.deployment.get("universe") or self.deployment.get("label"))
                or linux_user != (self.deployment.get("linux_user") or default_linux_user(self.deployment.get("label", "phoenix")))):
            self.output.append("[BLOCKED] This session's universe and Linux user are fixed by its deployment.")
            return

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
                if not retry and QtWidgets.QMessageBox.question(
                    self, f"{action.capitalize()} Universe",
                    f"{action.capitalize()} {universe} on {host} using the saved deployment?",
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No,
                ) != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
                if self.vault_connection is None:
                    self.output.append("[BLOCKED] The session vault connection is unavailable; nothing was sent.")
                    return
                intent = {"action": action, "universe": universe, "linux_user": linux_user,
                          "flags": flags, "capabilities": runtime_capabilities,
                          "bundle": encrypted_bundle}
                scope_key = request_scope_key(ssh_cfg, intent)
                if retry_request is not None and retry_request["scope_key"] != scope_key:
                    self.output.append("[BLOCKED] The deployment changed since this request; its previous options cannot be retried.")
                    return
                try:
                    request_id = self.vault_connection.request_railgun_identity(
                        action, flags, scope_key, new_operation=not retry)
                except RuntimeError as error:
                    self.output.append(f"[BLOCKED] {error}")
                    return
                if retry_request is not None and request_id != retry_request["request_id"]:
                    self.output.append("[BLOCKED] The saved request was replaced by a newer operation; this retry was not sent.")
                    return
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
            self.output.append(f"[SSH] Connecting to {host} as {user} via {auth_type}\n")

            worker = ControlSessionWorker(ssh_cfg, cmd, action, encrypted_bundle, swarm_key, self)
            if action != "stop":
                self._control_requests[action] = {
                    "flags": list(flags), "scope_key": scope_key, "request_id": request_id,
                }
                self._retry_control_actions[action].setEnabled(True)
                self.output.append(
                    "[REQUEST] Recovering the saved operation; a completed boot will not repeat.\n"
                    if retry else "[REQUEST] New operation saved before dispatch.\n"
                )
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
                    self.output.append("[UNKNOWN] SSH ended without an exit status. Use the matching button's Retry menu to recover the saved request.")
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
