from PyQt6.QtWidgets import QWidget, QFormLayout, QLineEdit, QComboBox, \
    QRadioButton, QButtonGroup, QVBoxLayout, QStackedWidget
from .base_editor import ConnectionEditorInterface

class EmailConnectionEditor(ConnectionEditorInterface):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn, default_channel_options)

        # === Identity ===
        self.proto = QLineEdit()
        self.serial = QLineEdit()
        self.label = QLineEdit()

        self._lock_proto_and_serial(self.proto, self.serial)
        self.proto.setText("email")

        self.default_channel = QComboBox()
        self.default_channel.addItems(default_channel_options or [])

        self.smtp_encryption = QComboBox()
        self.smtp_encryption.addItems(["SSL", "STARTTLS", "TLS", "None"])

        self.in_encryption = QComboBox()
        self.in_encryption.addItems(["SSL", "STARTTLS", "TLS", "None"])

        # === SMTP fields ===
        self.smtp_server = QLineEdit()
        self.smtp_port = QLineEdit()
        self.smtp_user = QLineEdit()
        self.smtp_pass = QLineEdit()
        self.smtp_to = QLineEdit()
        self.smtp_pass.setEchoMode(QLineEdit.EchoMode.Password)

        # === Incoming fields ===
        self.protocol = QComboBox()
        self.protocol.addItems(["IMAP", "POP3"])

        self.in_server = QLineEdit()
        self.in_port = QLineEdit()
        self.in_user = QLineEdit()
        self.in_pass = QLineEdit()
        self.in_pass.setEchoMode(QLineEdit.EchoMode.Password)

        # === Mode selection ===
        self.mode_group = QButtonGroup(self)
        self.out_radio = QRadioButton("Outgoing (SMTP)")
        self.in_radio = QRadioButton("Incoming (IMAP/POP3)")
        self.mode_group.addButton(self.out_radio)
        self.mode_group.addButton(self.in_radio)
        self.out_radio.setChecked(True)

        # === ROOT FORM ===
        self.layout = QFormLayout(self)
        self.layout.addRow("Protocol", self.proto)
        self.layout.addRow("Label", self.label)

        mode_box = QWidget()
        mlay = QVBoxLayout(mode_box)
        mlay.setContentsMargins(0, 0, 0, 0)
        mlay.addWidget(self.out_radio)
        mlay.addWidget(self.in_radio)
        self.layout.addRow("Type", mode_box)

        # === STACK BUILT ONCE ===
        self.stack = QStackedWidget()
        self.layout.addRow(self.stack)

        # --- Outgoing page ---
        out_page = QWidget()
        out_form = QFormLayout(out_page)
        out_form.addRow("SMTP Server", self.smtp_server)
        out_form.addRow("SMTP Port", self.smtp_port)
        out_form.addRow("Send To", self.smtp_to)
        out_form.addRow("Username", self.smtp_user)
        out_form.addRow("Password", self.smtp_pass)
        out_form.addRow("Encryption", self.smtp_encryption)
        self.stack.addWidget(out_page)

        # --- Incoming page ---
        in_page = QWidget()
        in_form = QFormLayout(in_page)
        in_form.addRow("Protocol", self.protocol)
        in_form.addRow("Incoming Server", self.in_server)
        in_form.addRow("Incoming Port", self.in_port)
        in_form.addRow("Username", self.in_user)
        in_form.addRow("Password", self.in_pass)
        in_form.addRow("Encryption", self.in_encryption)
        self.stack.addWidget(in_page)

        self.layout.addRow("Default Channel", self.default_channel)
        self.layout.addRow("Serial", self.serial)

        # events
        self.out_radio.toggled.connect(self._render_mode)

    # --------------------------------
    def _render_mode(self):
        self.stack.setCurrentIndex(0 if self.out_radio.isChecked() else 1)

    # --------------------------------
    def on_load(self, data):
        self.proto.setText("email")
        self.serial.setText(data.get("serial", ""))

        self.label.setText(data.get("label", ""))
        self.default_channel.setCurrentText(data.get("default_channel", ""))

        mode = data.get("type", "outgoing")

        if mode == "incoming":
            self.in_radio.setChecked(True)
            self.stack.setCurrentIndex(1)

            self.protocol.setCurrentText(data.get("protocol", "IMAP"))
            self.in_server.setText(data.get("incoming_server", ""))
            self.in_port.setText(str(data.get("incoming_port", "")))
            self.in_user.setText(data.get("incoming_username", ""))
            self.in_pass.setText(data.get("incoming_password", ""))
            self.in_encryption.setCurrentText(data.get("incoming_encryption", "SSL"))

        else:
            self.out_radio.setChecked(True)
            self.stack.setCurrentIndex(0)

            self.smtp_server.setText(data.get("smtp_server", ""))
            self.smtp_port.setText(str(data.get("smtp_port", "")))
            self.smtp_user.setText(data.get("smtp_username", ""))
            self.smtp_pass.setText(data.get("smtp_password", ""))
            self.smtp_to.setText(data.get("smtp_to", ""))
            self.smtp_encryption.setCurrentText(data.get("smtp_encryption", "SSL"))

    # --------------------------------
    def serialize(self):
        self._ensure_serial()

        out = {
            "proto": "email",
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "default_channel": self.default_channel.currentText(),
        }

        if self.out_radio.isChecked():
            out.update({
                "type": "outgoing",
                "smtp_server": self.smtp_server.text().strip(),
                "smtp_port": int(self.smtp_port.text() or 0),
                "smtp_to": self.smtp_to.text().strip(),
                "smtp_username": self.smtp_user.text().strip(),
                "smtp_password": self.smtp_pass.text().strip(),
                "smtp_encryption": self.smtp_encryption.currentText(),
            })
        else:
            out.update({
                "type": "incoming",
                "protocol": self.protocol.currentText(),
                "incoming_server": self.in_server.text().strip(),
                "incoming_port": int(self.in_port.text() or 0),
                "incoming_username": self.in_user.text().strip(),
                "incoming_password": self.in_pass.text().strip(),
                "incoming_encryption": self.in_encryption.currentText(),
            })

        return out

    # --------------------------------
    def validate(self):
        ok, msg = self._require_proto_and_serial()
        if not ok:
            return ok, msg

        if not self.label.text().strip():
            return False, "Label is required."

        if not self.default_channel.currentText().strip():
            return False, "Default channel is required."

        if self.out_radio.isChecked():
            if not self.smtp_server.text().strip():
                return False, "SMTP Server required."
            if not self.smtp_port.text().isdigit():
                return False, "SMTP Port must be numeric."
        else:
            if not self.in_server.text().strip():
                return False, "Incoming Server required."
            if not self.in_port.text().isdigit():
                return False, "Incoming Port must be numeric."
        if not self.in_encryption.currentText():
            return False, "Encryption mode required."

        return True, ""
