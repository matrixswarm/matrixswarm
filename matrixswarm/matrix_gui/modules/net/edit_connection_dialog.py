import uuid
import ipaddress
from PyQt5 import QtWidgets

def edit_connection_dialog(parent, default_proto="https", data=None, conn_id=None):
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("Edit Connection")
    dlg.setMinimumWidth(420)

    layout = QtWidgets.QFormLayout(dlg)
    fields = {}

    type_selector = QtWidgets.QComboBox()
    type_selector.addItems(["https", "wss", "discord", "telegram", "openai", "email", "slack"])
    layout.addRow("Connection Type", type_selector)

    pre_proto = (data or {}).get("proto", default_proto)
    idx = type_selector.findText(pre_proto)
    if idx >= 0:
        type_selector.setCurrentIndex(idx)

    field_widgets = QtWidgets.QWidget()
    field_layout = QtWidgets.QFormLayout(field_widgets)
    layout.addRow(field_widgets)

    def clear_fields():
        for i in reversed(range(field_layout.count())):
            widget = field_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        fields.clear()

    def add_field(name, default=""):
        box = QtWidgets.QLineEdit()
        if data:
            val = data.get(name, default)
            if name == "allowlist_ips" and isinstance(val, list):
                val = ", ".join(val)
            box.setText(str(val))
        else:
            box.setText(str(default))
        if name == "serial":
            box.setReadOnly(True)
        field_layout.addRow(name.replace("_", " ").title(), box)
        fields[name] = box

    def update_fields_for_type():
        clear_fields()
        p = type_selector.currentText()
        add_field("label")

        if p in ("https", "wss"):
            add_field("host")
            add_field("port")
            add_field("purpose")
            add_field("note")
            add_field("allowlist_ips")
        elif p == "discord":
            add_field("channel_id")
            add_field("bot_token")
            add_field("note")
        elif p == "telegram":
            add_field("chat_id")
            add_field("bot_token")
            add_field("note")
        elif p == "email":
            add_field("smtp_server")
            add_field("username")
            add_field("note")
        elif p == "openai":
            add_field("api_key")
            add_field("note")
        elif p == "slack":
            add_field("webhook_url")
            add_field("note")

        # Default channel role dropdown
        channel_box = QtWidgets.QComboBox()
        if p == "https":
            channel_box.addItems(["outgoing.command"])
        elif p == "wss":
            channel_box.addItems(["payload.reception"])
        elif p == "discord":
            channel_box.addItems(["alerts"])
        elif p == "telegram":
            channel_box.addItems(["alerts"])
        elif p == "openai":
            channel_box.addItems(["oracle"])
        elif p == "email":
            channel_box.addItems(["alerts"])
        elif p == "slack":
            channel_box.addItems(["alerts"])
        else:
            channel_box.addItems(["outgoing.command"])

        prev_default = (data or {}).get("default_channel")
        if prev_default:
            idx = channel_box.findText(prev_default)
            if idx >= 0:
                channel_box.setCurrentIndex(idx)

        field_layout.addRow("Default Channel Role", channel_box)
        fields["default_channel"] = channel_box

        # Always attach/generate a serial
        serial = str((data or {}).get("serial") or uuid.uuid4().hex[:8])
        add_field("serial", default=serial)

    def validate_and_return():
        result = {"proto": type_selector.currentText()}

        required_fields = ["label"]
        proto = result["proto"]

        if proto in ("https", "wss"):
            required_fields += ["host", "port"]
        elif proto == "discord":
            required_fields += ["channel_id"]
        elif proto == "telegram":
            required_fields += ["chat_id"]
        elif proto == "email":
            required_fields += ["smtp_server"]
        elif proto == "slack":
            required_fields += ["webhook_url"]

        for key in required_fields:
            widget = fields.get(key)
            if not widget or not widget.text().strip():
                QtWidgets.QMessageBox.warning(dlg, "Missing Field", f"'{key.replace('_', ' ').title()}' is required.")
                return None, None
            if key in ("port", "channel_id", "chat_id"):
                if not widget.text().strip().isdigit():
                    QtWidgets.QMessageBox.warning(dlg, "Invalid Input",
                                                  f"{key.replace('_', ' ').title()} must be numeric.")
                    return None, None

        # build result
        for k, widget in fields.items():
            val=None
            if isinstance(widget, QtWidgets.QComboBox):
                result[k] = widget.currentText()
            else:
                val = widget.text().strip()
            if val:
                if k in ("port", "channel_id", "chat_id"):
                    result[k] = int(val)
                elif k == "allowlist_ips":
                    ips = [x.strip() for x in val.split(",") if x.strip()]
                    bad = []
                    good = []
                    for ip in ips:
                        try:
                            ipaddress.ip_address(ip)
                            good.append(ip)
                        except ValueError:
                            bad.append(ip)
                    if bad:
                        QtWidgets.QMessageBox.warning(
                            dlg, "Invalid IPs",
                            f"The following entries are not valid IP addresses:\n{', '.join(bad)}"
                        )
                        return None, None
                    result[k] = good
                else:
                    result[k] = val

        # generate conn_id if new
        new_id = conn_id or f"conn_{result['proto']}_{result.get('label','unnamed').lower().replace(' ', '_')}"
        return new_id, result

    def on_accept():
        out = validate_and_return()
        if out is not None:
            new_id, result = out
            dlg._return_id = new_id
            dlg._return_data = result
            dlg.accept()

    type_selector.currentTextChanged.connect(update_fields_for_type)
    update_fields_for_type()

    btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    layout.addRow(btns)
    btns.accepted.connect(on_accept)
    btns.rejected.connect(dlg.reject)

    if dlg.exec_() != QtWidgets.QDialog.Accepted:
        return None, None

    return dlg._return_id, dlg._return_data
