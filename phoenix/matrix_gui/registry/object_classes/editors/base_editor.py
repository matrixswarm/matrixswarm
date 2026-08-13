from abc import ABCMeta, abstractmethod
from PyQt6.QtWidgets import QWidget,  QLineEdit, QComboBox, QDialog, QVBoxLayout, QDialogButtonBox
import uuid, random

class EditorABCMeta(type(QWidget), ABCMeta):
    pass

class BaseEditor(QWidget, metaclass=EditorABCMeta):

    def __init__(self, parent=None, default_channel_options=None):
        super().__init__(parent)
        self._default_channel_options = default_channel_options or []
        self._serial_widget = None
        self.serial = QLineEdit()
        self._lock_serial(self.serial)
        self._ensure_serial()

    # ---------------------------------------------------------
    # Built-in lifecycle: LOAD
    # ---------------------------------------------------------
    def _load_data(self, data: dict):
        """Internal load handler that guarantees lifecycle correctness."""
        self._is_new = False
        self.on_load(data)

    @abstractmethod
    def on_load(self, data: dict):
        """
        Concrete editors implement this — but cannot touch _is_new.
        Base class sets _is_new = False before calling this.
        """
        pass

    def is_connection(self)->bool:
        """
        Is this a connection? Have Ip
        """
        return False

    # ---------------------------------------------------------
    # SERIAL ENFORCEMENT ONLY (PROTO REMOVED)
    # ---------------------------------------------------------
    def _lock_serial(self, serial_widget: QLineEdit):
        """Commander Edition: lock and ensure serial presence."""
        self._serial_widget = serial_widget


        serial = str(self._gen_serial_32())
        self._serial_widget.setText(serial)
        self._serial = serial

        serial_widget.setReadOnly(True)
        serial_widget.setStyleSheet("color:#888; background-color:#222;")

    def _gen_serial_32(self):
        return uuid.uuid4().hex[:32]

    def _ensure_serial(self):
        if not self._serial_widget:
            raise RuntimeError("Serial widget not attached.")
        if not self._serial_widget.text().strip():
            new = self._gen_serial_32()
            self._serial_widget.setText(new)
            return new
        return self._serial_widget.text().strip()


    def generate_default_label(self):
        class_name_lower = self.__class__.__name__.lower()  # Get lowercase class name
        random_hex = format(random.randint(0, 0xFFFFF), '05X')  # Generate random hex
        return f"{class_name_lower}_{random_hex}"

    def _require_serial(self):
        serial = self._serial_widget.text().strip()

        if not serial:
            return False, "Serial is required."

        if not len(serial) == 32:
            return False, "Serial must be 32 hex hex digits."

        return True, ""
    # ---------------------------------------------------------
    # Data API
    # ---------------------------------------------------------
    @abstractmethod
    def serialize(self) -> dict:
        pass

    @abstractmethod
    def is_validated(self) -> bool:
        pass

    # Path override
    def get_directory_path(self):
        """
        Returns the selected directory path as a list.
        Example: "config/imap_bk" → ["config", "imap_bk"]
        """
        r=["config"]
        try:
            value = self.path_selector.currentText().strip()
            #dd=value.split("/")
            #print(f"Success: 'path_selector' is defined for {dd}")
            r=value.split("/")

        except AttributeError as e:
            print(f"Error: 'path_selector' is not defined or is not a QComboBox. {e}")

        finally:
            return r


    def get_serial(self)-> str:
        return self.serial.text().strip()

    def deploy_fields(self):
        """
        Returns only fields intended for deploy-time consumption.
        Editors MUST override this to remove UI-only garbage like
        label, note, default_channel, etc.
        """
        return self.serialize()

    def directive_fields(self):
        return {}

    def is_autogen(self) -> bool:
        """
        Commander Edition:
        Indicates this editor generates data automatically at deploy-time
        and is not user-editable or registry-backed.
        """
        return False

    def exec(self):
        """Commander Edition — wrap the editor in a modal dialog with OK/Cancel."""
        dialog = QDialog()
        dialog.setWindowTitle(self.__class__.__name__)
        dialog.setMinimumWidth(480)

        # --- Layout ---
        layout = QVBoxLayout(dialog)
        layout.addWidget(self)

        # --- Buttons (Commander Confirm Panel) ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )

        def on_ok():
            valid, msg = self.is_validated()
            if not valid:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Invalid Entry", msg)
                return
            dialog.accept()

        buttons.accepted.connect(on_ok)
        buttons.rejected.connect(dialog.reject)

        # Optional Commander styling
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #111;
                color: #ddd;
                border: 1px solid #444;
                padding: 4px 12px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover { background-color: #1f1f1f; }
            QPushButton:pressed { background-color: #222; }
        """)

        layout.addWidget(buttons)

        # --- Execute and return dialog result ---
        return dialog.exec()
