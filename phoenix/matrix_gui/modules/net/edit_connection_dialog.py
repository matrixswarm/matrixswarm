from PyQt6.QtWidgets import QDialogButtonBox
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from matrix_gui.modules.net.connection_types.providers.registry import CONNECTION_PROVIDER_REGISTRY
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.net.connection_types.editors.registry import CONNECTION_EDITOR_REGISTRY

def edit_connection_dialog(parent, default_proto="https", data:dict=None, conn_id=None, new_conn=False):
    """
    ALWAYS returns:
        (conn_id, data_dict)
    OR:
        (None, None)
    """

    try:

        proto = data.get("proto", default_proto) if data and isinstance(data,dict) else default_proto

        # ----------------------------------------
        # FAIL SAFETY: Editing but no data provided
        # ----------------------------------------
        if not new_conn:
            if not data or not isinstance(data, dict) or len(data.keys()) == 0:
                QMessageBox.critical(
                    parent,
                    "Connection Error",
                    "Attempted to edit a connection but no data was provided.\n"
                    "This indicates an internal logic error in the caller."
                )
                return (None, None)

        dlg = QDialog(parent)
        dlg.setWindowTitle(f"Edit {proto.upper()} Connection")

        provider = CONNECTION_PROVIDER_REGISTRY.get(proto)
        channel_options = provider.get_default_channel_options()

        editor_cls = CONNECTION_EDITOR_REGISTRY.get(proto)
        if not editor_cls:
            QMessageBox.critical(parent, "Unknown Protocol", f"No editor for protocol '{proto}'")
            return (None, None)

        editor = editor_cls(
            parent=dlg,
            new_conn=new_conn,
            default_channel_options=channel_options
        )
        if data:
            editor._load_data(data)  # base class handles lifecycle
        else:
            editor._is_new = True  # enforce creation mode
            editor.on_create()

        layout = QVBoxLayout(dlg)
        layout.addWidget(editor)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(btns)

        # --- OK handler ---
        def on_ok():
            valid, reason = editor.validate()
            if not valid:
                QMessageBox.warning(dlg, "Invalid Configuration", reason)
                return

            new_data = editor.serialize()
            # enforce auto-label if missing
            if not new_data.get("label", "").strip():
                new_data["label"] = editor._generate_auto_label(proto, new_data)

            # ID stays serial
            new_id = new_data["serial"]

            dlg.result = (new_id, new_data)
            dlg.accept()

        btns.accepted.connect(on_ok)

        # --- CANCEL handler ---
        def on_cancel():
            dlg.result = (None, None)  # Always provide tuple
            dlg.reject()  # SAFE: triggers close

        btns.rejected.connect(on_cancel)

        # --- HANDLE WINDOW X BUTTON (titlebar close) ---
        def closeEvent(event):
            # If user clicks X without OK/Cancel
            if not hasattr(dlg, "result"):
                dlg.result = (None, None)
            event.accept()  # required or window won't close

        dlg.closeEvent = closeEvent

        dlg.exec()

        # FORCE EXACT RETURN FORMAT:
        return getattr(dlg, "result", (None, None))

    except Exception as e:
        emit_gui_exception_log("edit_connection_dialog", e)
