# Authored by Daniel F MacDonald & ChatGPT-5 aka The Generals
from PyQt6 import QtWidgets, QtCore
from matrix_gui.modules.railgun.ssh_support import (
    connect_ssh_profile,
    format_ssh_profile_label,
)
from matrix_gui.modules.railgun.remote_shell import (
    build_remote_matrixd_command,
    default_linux_user,
    describe_runtime_capabilities,
    derive_runtime_capabilities,
    mcp_worker_linux_user,
    send_boot_envelope,
    validate_linux_user,
    validate_remote_token,
    verify_remote_matrixd_stdin,
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

        btns.addStretch(1)

        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        btns.addWidget(close)

        self.layout.addLayout(btns)

    # ----------------------------------------------------
    def _run_remote(self, action: str):
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
            cmd = build_remote_matrixd_command(
                action=action,
                universe=universe,
                linux_user=linux_user,
                boot_flags=flags,
                runtime_capabilities=runtime_capabilities,
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

            try:
                client, actual_fingerprint = connect_ssh_profile(ssh_cfg)
                self.output.append(
                    f"[SSH] Host fingerprint verified: "
                    f"{actual_fingerprint}\n"
                )
                if action != "stop":
                    verify_remote_matrixd_stdin(client)
                    self.output.append(
                        "[RAILGUN] Remote MatrixD sealed-stream capability "
                        "verified.\n"
                    )

                transport = client.get_transport()
                chan = transport.open_session()
                chan.exec_command(cmd)
                if action != "stop":
                    payload_size = send_boot_envelope(
                        chan, encrypted_bundle, swarm_key
                    )
                    self.output.append(
                        f"[RAILGUN] Streamed sealed boot envelope "
                        f"({payload_size} bytes); no remote boot files created.\n"
                    )

                # store references so poller can read them
                self._ssh_client = client
                self._active_channel = chan

                # START POLLING (no while loop!!)
                self._poll_timer = QtCore.QTimer(self)
                self._poll_timer.timeout.connect(self._poll_ssh_channel)
                self._poll_timer.start(120)

            except Exception as e:
                self.output.append(f"[ERROR] {e}\n")

        except Exception as e:
            self.output.append(f"[ERROR] {e}")

    def _poll_ssh_channel(self):
        chan = getattr(self, "_active_channel", None)
        if chan is None:
            if self._poll_timer is not None:
                self._poll_timer.stop()
            return

        try:
            # Drain the SSH window fully so boot output cannot back-pressure
            # the remote matrixd process.
            while chan.recv_ready():
                data = chan.recv(4096).decode(errors="ignore")
                self.output.append(data)

            while chan.recv_stderr_ready():
                data = chan.recv_stderr(4096).decode(errors="ignore")
                self.output.append(f"<span style='color:red'>{data}</span>")

            # Finished?
            if chan.exit_status_ready():
                code = chan.recv_exit_status()
                self.output.append(f"\n[Exit {code}] remote action complete.\n")
                self._close_ssh_session()

        except Exception as e:
            self.output.append(f"[ERROR] SSH stream: {e}")
            self._close_ssh_session()

    def _close_ssh_session(self):
        if self._poll_timer is not None:
            self._poll_timer.stop()

        chan = self._active_channel
        self._active_channel = None
        if chan is not None:
            try:
                chan.close()
            except Exception:
                pass

        client = self._ssh_client
        self._ssh_client = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def closeEvent(self, event):
        self._close_ssh_session()
        super().closeEvent(event)
