from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QMessageBox
from copy import deepcopy
import math
import logging
import traceback
from PyQt6.QtCore import Qt

def log_editor_failure(operation, exc):
    """Record diagnostic locations without exception messages, locals or config."""
    frames = traceback.extract_tb(exc.__traceback__)
    locations = "\n".join(f"  {frame.filename}:{frame.lineno} in {frame.name}" for frame in frames)
    logging.getLogger(__name__).error("Editor %s failed: %s\n%s", operation, type(exc).__name__, locations)

class BaseEditor(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node = node
        self.config = node.config
        self.inputs = {}
        self._original_scalars = {}

        self.setWindowTitle(f"{node.get_name()} Config Editor")
        self.layout = QFormLayout(self)
        self._build_form()

        btns = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.cancel_btn = QPushButton("Cancel")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        self.layout.addRow(btns)

        self.save_btn.clicked.connect(self._save_safely)
        self.cancel_btn.clicked.connect(self.reject)

    def _save_safely(self):
        """Keep unexpected editor exceptions inside the Qt callback boundary."""
        before = deepcopy(self.node.config)
        dirty = self.node._dirty
        try:
            self._save()
        except Exception as exc:
            log_editor_failure("save", exc)
            if isinstance(self.node.config, dict) and isinstance(before, dict):
                self.node.config.clear()
                self.node.config.update(before)
            else:
                self.node.config = before
            self.config = self.node.config
            self.node._dirty = dirty
            QMessageBox.critical(self, "Configuration Save Failed",
                                 f"The editor failed ({type(exc).__name__}). "
                                 "Configuration changes were rolled back. Diagnostic stack locations were logged. "
                                 "Correct the input or cancel.")

    def _build_form(self):
        # Default: simple key/value editors for flat dict configs
        for k, v in self.config.items():
            if isinstance(v, (dict, list)):  # skip complex nested
                continue
            field = QLineEdit(str(v))
            self._original_scalars[k] = deepcopy(v)
            self.layout.addRow(k, field)
            self.inputs[k] = field

    @staticmethod
    def _load_saved_text(widget, value):
        valid = isinstance(value, str)
        widget.setText(value if valid else "")
        widget.setProperty("invalidSavedText", not valid)
        if not valid:
            widget.setPlaceholderText("Invalid saved value — enter replacement")
            widget.setToolTip(f"Invalid saved value: {value!r}")
        widget.textChanged.connect(lambda _: widget.setProperty("invalidSavedText", False))

    @staticmethod
    def _saved_text(widget, name):
        if widget.property("invalidSavedText"):
            raise ValueError(f"{name}: replace the invalid saved value with text.")
        return widget.text()

    @staticmethod
    def _load_saved_bool(widget, value):
        if type(value) is bool:
            widget.setChecked(value)
        else:
            widget.setTristate(True)
            widget.setCheckState(Qt.CheckState.PartiallyChecked)
            widget.setToolTip(f"Invalid saved value: {value!r}. Choose checked or unchecked.")

    @staticmethod
    def _saved_bool(widget, name):
        if widget.checkState() == Qt.CheckState.PartiallyChecked:
            raise ValueError(f"{name}: explicitly choose checked or unchecked.")
        return widget.isChecked()

    @staticmethod
    def _load_saved_number(widget, value):
        """Keep imported numbers lossless; never silently save a clamped value."""
        valid = type(value) in (int, float) and math.isfinite(value)
        if not hasattr(widget, "decimals"):
            valid = valid and type(value) is int
        valid = valid and widget.minimum() <= value <= widget.maximum()
        widget.setProperty("savedNumber", value if valid else None)
        widget.setProperty("invalidSavedNumber", not valid)
        widget.setProperty("numberEdited", False)
        if valid:
            widget.setValue(value)
        else:
            widget.setToolTip(f"Invalid saved value: {value!r}. Choose a valid value before saving.")
        widget.valueChanged.connect(lambda _: widget.setProperty("numberEdited", True))

    @staticmethod
    def _saved_number(widget, name):
        if not widget.property("numberEdited"):
            if widget.property("invalidSavedNumber"):
                raise ValueError(f"{name}: invalid saved value; choose a value between "
                                 f"{widget.minimum()} and {widget.maximum()} before saving.")
            return widget.property("savedNumber")
        return widget.value()

    @staticmethod
    def _select_saved_choice(combo, value):
        """Display persisted choices even when newer than this UI's presets."""
        if not isinstance(value, str) or not value.strip():
            combo.addItem("Invalid saved value — select a replacement")
            combo.setCurrentIndex(combo.count() - 1)
            combo.setProperty("invalidChoiceIndex", combo.currentIndex())
            combo.setToolTip(f"Invalid saved value: {value!r}")
            return
        if combo.findText(value) < 0:
            combo.addItem(value)
        combo.setCurrentText(value)

    @staticmethod
    def _saved_choice(combo, name):
        if combo.property("invalidChoiceIndex") == combo.currentIndex():
            raise ValueError(f"{name}: select a valid replacement for the invalid saved value.")
        return combo.currentText()

    def _save(self):
        changes = {}
        try:
            for k, widget in self.inputs.items():
                original = self._original_scalars[k]
                text = widget.text()
                if text == str(original):
                    changes[k] = original
                elif type(original) is bool:
                    if text.strip().lower() not in {"true", "false"}:
                        raise ValueError(f"{k}: enter true or false")
                    changes[k] = text.strip().lower() == "true"
                elif type(original) is int:
                    changes[k] = int(text)
                elif type(original) is float:
                    changes[k] = float(text)
                    if not math.isfinite(changes[k]):
                        raise ValueError(f"{k}: enter a finite number")
                elif original is None:
                    if text.strip().lower() not in {"none", "null"}:
                        raise ValueError(f"{k}: this field has no configured type; retain null")
                    changes[k] = None
                else:
                    changes[k] = text.strip()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid Configuration", str(exc))
            return
        self.node.config.update(changes)
        self.node.mark_dirty()
        self.accept()
