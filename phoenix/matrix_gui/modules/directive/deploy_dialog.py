# Authored by Daniel F MacDonald & ChatGPT-5 aka The Generals
import os
from PyQt6 import QtWidgets, QtCore
from matrix_gui.modules.railgun.ssh_support import connect_ssh_profile
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
            name = meta.get("label", sid)
            host = meta.get("host", "?")
            display = f"{name} ({host})"
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
            self.universe_edit.setText(self.deployment.get("label", ""))

        opts_layout.addWidget(QtWidgets.QLabel("Universe:"))
        opts_layout.addWidget(self.universe_edit)

        # Directive dropdown
        self.directive_dropdown = QtWidgets.QComboBox()
        self.directive_dropdown.addItem(
            os.path.basename(self.deployment.get("encrypted_path", "")),
            self.deployment.get("encrypted_path")
        )
        opts_layout.addWidget(QtWidgets.QLabel("Directive File:"))
        opts_layout.addWidget(self.directive_dropdown)

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

        flag_row = QtWidgets.QHBoxLayout()
        for f in (self.flag_verbose, self.flag_debug, self.flag_clean,
                  self.flag_rugpull, self.flag_reboot_new):
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
        swarm_key = self.deployment["swarm_key"]
        directive_name = self.deployment["encrypted_path"]
        # Collect options
        universe = self.universe_edit.text().strip() or self.deployment["label"]
        directive_path = self.directive_dropdown.currentData()
        directive_file = os.path.basename(directive_path)

        flags = []
        if self.flag_debug.isChecked(): flags.append("--debug")
        if self.flag_clean.isChecked(): flags.append("--clean")
        if self.flag_rugpull.isChecked(): flags.append("--rug-pull")
        if self.flag_reboot_new.isChecked(): flags.append("--reboot-new")
        flag_str = " ".join(flags)

        self.output.append(f"[SSH] Connecting to {host} as {user} via {auth_type}\n")

        try:

            if directive_name:
                directive_leaf = str(directive_name).replace("\\", "/").rsplit("/", 1)[-1]
                directive_remote = f"/matrix/boot_directives/{directive_leaf}"
            else:
                directive_remote = f"/matrix/boot_directives/{universe}.enc.json"

            if not swarm_key:
                self.output.append("[ERROR] No SWARM_KEY available for this deployment.\n")
                return

            if action == "start":
                directive_remote = f"/matrix/boot_directives/{directive_file}"

                cmd = (
                    f"cd /matrix && "
                    f"export SITE_ROOT=/matrix && "
                    f"export SWARM_KEY='{swarm_key}' && "
                    f"if [ -f /matrix/.venv/bin/activate ]; then . /matrix/.venv/bin/activate; fi && "
                    f"matrixd boot --universe {universe} --directive {directive_remote} {flag_str}"
                )

            elif action == "restart":
                cmd = (
                    f"cd /matrix && "
                    f"export SITE_ROOT=/matrix && "
                    f"export SWARM_KEY='{swarm_key}' && "
                    f"if [ -f /matrix/.venv/bin/activate ]; then . /matrix/.venv/bin/activate; fi && "
                    f"matrixd kill --universe {universe} && "
                    f"matrixd boot --universe {universe} --directive {directive_remote} {flag_str}"
                )
            elif action == "stop":
                cmd = (
                    f"cd /matrix && "
                    f"export SITE_ROOT=/matrix && "
                    f"if [ -f /matrix/.venv/bin/activate ]; then . /matrix/.venv/bin/activate; fi && "
                    f"matrixd kill --universe {universe}"
                )

            display_cmd = cmd.replace(str(swarm_key), "[REDACTED]")
            self.output.append(f"[CMD] {display_cmd}\n")

            try:
                client, actual_fingerprint = connect_ssh_profile(ssh_cfg)
                self.output.append(
                    f"[SSH] Host fingerprint verified: "
                    f"{actual_fingerprint}\n"
                )

                transport = client.get_transport()
                chan = transport.open_session()
                chan.exec_command(cmd)

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
