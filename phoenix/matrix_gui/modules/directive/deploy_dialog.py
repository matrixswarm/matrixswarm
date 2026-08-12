# Authored by Daniel F MacDonald & ChatGPT-5 aka The Generals
import io, os, paramiko
from PyQt6 import QtWidgets, QtCore
QtCore.QCoreApplication.processEvents()
class DeployDialog(QtWidgets.QDialog):
    """Railgun-style MatrixD controller over SSH, with SSH selector."""

    def __init__(self, ssh_map, default_serial=None, deployment=None, parent=None):
        super().__init__(parent)

        self.setWindowTitle("MatrixD Control")
        self.resize(700, 520)

        self.ssh_map = ssh_map
        self.deployment = deployment or {}
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
        password = ssh_cfg.get("password")
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
        if self.flag_verbose.isChecked(): flags.append("--verbose")
        if self.flag_debug.isChecked(): flags.append("--debug")
        if self.flag_clean.isChecked(): flags.append("--clean")
        if self.flag_rugpull.isChecked(): flags.append("--rug-pull")
        if self.flag_reboot_new.isChecked(): flags.append("--reboot-new")
        flag_str = " ".join(flags)

        self.output.append(f"[SSH] Connecting to {host} as {user} via {auth_type}\n")

        try:

            if directive_name:
                directive_remote = f"/matrix/boot_directives/{directive_name.split('boot_directives')[-1].replace('\\\\', '/').split('/')[-1]}"
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
                    f"[ -d venv ] && source venv/bin/activate || true && "
                    f"matrixd boot --universe {universe} --directive {directive_remote} {flag_str}"
                )

            elif action == "restart":
                cmd = (
                    f"cd /matrix && "
                    f"export SITE_ROOT=/matrix && "
                    f"export SWARM_KEY='{swarm_key}' && "
                    f"[ -d venv ] && source venv/bin/activate || true && "
                    f"matrixd kill --universe {universe} && "
                    f"matrixd boot --universe {universe} --directive {directive_remote} {flag_str}"
                )
            elif action == "stop":
                cmd = (
                    f"cd /matrix && "
                    f"export SITE_ROOT=/matrix && "
                    f"[ -d venv ] && source venv/bin/activate || true && "
                    f"matrixd kill --universe {universe}"
                )

            self.output.append(f"[CMD] {cmd}\n")

            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                if auth_type == "password":
                    client.connect(
                        host,
                        port=port,
                        username=user,
                        password=password,
                        look_for_keys=False,
                        allow_agent=False
                    )

                elif auth_type == "private_key":
                    key = paramiko.RSAKey.from_private_key(io.StringIO(privkey_pem))
                    client.connect(
                        host,
                        port=port,
                        username=user,
                        pkey=key,
                        look_for_keys=False,
                        allow_agent=False
                    )

                elif auth_type == "agent":
                    client.connect(
                        host,
                        port=port,
                        username=user,
                        allow_agent=True
                    )

                transport = client.get_transport()
                chan = transport.open_session()
                chan.get_pty()
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
            self._poll_timer.stop()
            return

        try:
            # STDOUT
            if chan.recv_ready():
                data = chan.recv(4096).decode(errors="ignore")
                self.output.append(data)

            # STDERR
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(4096).decode(errors="ignore")
                self.output.append(f"<span style='color:red'>{data}</span>")

            # Finished?
            if chan.exit_status_ready():
                code = chan.recv_exit_status()
                self.output.append(f"\n[Exit {code}] remote action complete.\n")

                self._poll_timer.stop()
                self._active_channel = None
                chan.close()

        except Exception as e:
            self.output.append(f"[ERROR] SSH stream: {e}")
            self._poll_timer.stop()
            self._active_channel = None
