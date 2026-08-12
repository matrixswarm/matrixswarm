# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition – AgentPropertyDialog rebuilt for AgentNode
import json
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLabel, QLineEdit, QTextEdit,
    QComboBox, QPushButton, QMessageBox
)
from PyQt6.QtGui import QIntValidator, QRegularExpressionValidator
from PyQt6.QtCore import QRegularExpression
from matrix_gui.registry.registry_singleton import RegistrySingleton


class AgentPropertyDialog(QDialog):
    """
    Commander Edition — Clean, correct AgentPropertyDialog for AgentNode (class-based).
    """

    def __init__(self, node, parent=None):
        super().__init__(parent)

        self.node = node
        self.meta = node.meta or {}
        self.registry = RegistrySingleton.get()

        self.setWindowTitle(f"{node.get_name()} Properties")
        layout = QFormLayout(self)

        self.inputs = {}

        # ---------------------------------------------------------
        # Universal ID (read-only)
        # ---------------------------------------------------------
        uid = QLineEdit(node.get_universal_id())
        uid.setReadOnly(True)
        layout.addRow("Universal ID:", uid)
        self.inputs["_uid"] = uid

        # ---------------------------------------------------------
        # Dynamic meta fields
        # ---------------------------------------------------------
        params = node.get_params()

        for fname, spec in self.meta.get("fields", {}).items():
            widget = self._make_widget(fname, spec)

            # Load current value
            val = params.get(fname)
            if isinstance(widget, QLineEdit) and val is not None:
                widget.setText(str(val))

            elif isinstance(widget, QComboBox) and val is not None:
                widget.setCurrentText(str(val))

            elif isinstance(widget, QTextEdit) and val is not None:
                widget.setPlainText(json.dumps(val, indent=2))

            layout.addRow(fname, widget)
            self.inputs[fname] = widget

        # ---------------------------------------------------------
        # Save button
        # ---------------------------------------------------------
        btn = QPushButton("Save")
        btn.clicked.connect(self._save)
        layout.addRow(btn)

    # -------------------------------------------------------------
    # Widget Factory
    # -------------------------------------------------------------
    def _make_widget(self, name, spec):
        t = spec.get("type", "string")

        if t == "string":
            return QLineEdit()

        if t == "int":
            w = QLineEdit()
            w.setValidator(QIntValidator(spec.get("min", -999999), spec.get("max", 999999)))
            return w

        if t == "enum":
            w = QComboBox()
            w.addItems([str(x) for x in spec.get("values", [])])
            return w

        if t == "bool":
            w = QComboBox()
            w.addItems(["true", "false"])
            return w

        if t == "json":
            return QTextEdit()

        if t == "zipcode":
            w = QLineEdit()
            w.setValidator(QRegularExpressionValidator(
                QRegularExpression(r"^\d{5}(-\d{4})?$")
            ))
            return w

        if t == "shared":
            # Registry-backed field
            w = QComboBox()

            ns = spec.get("namespace")
            namespace_entries = self.registry.get_namespace(ns)

            for key, obj in namespace_entries.items():
                label = obj.get("label", key)
                w.addItem(label, f"{ns}.{key}")

            return w

        return QLineEdit()

    # -------------------------------------------------------------
    # Save Logic
    # -------------------------------------------------------------
    def _save(self):
        errors = []

        # --- Params ---
        params = {}
        for fname, spec in self.meta.get("fields", {}).items():
            widget = self.inputs[fname]
            t = spec.get("type", "string")

            # Extract value
            if isinstance(widget, QLineEdit):
                v = widget.text().strip()

            elif isinstance(widget, QComboBox):
                raw_v = widget.currentText().strip()
                v = (raw_v == "true") if t == "bool" else raw_v

            elif isinstance(widget, QTextEdit):
                raw_json = widget.toPlainText().strip()
                try:
                    v = json.loads(raw_json) if raw_json else {}
                except:
                    errors.append(f"{fname}: invalid JSON.")
                    continue

            else:
                v = None

            # Shared registry-backed
            if t == "shared":
                v = widget.currentData()

            # Required field?
            if spec.get("required") and not v:
                errors.append(f"{fname} is required.")

            params[fname] = v

        if errors:
            QMessageBox.warning(self, "Validation Errors", "\n".join(errors))
            return

        # Write params into node
        self.node.params = params
        self.node.mark_dirty()

        self.accept()

