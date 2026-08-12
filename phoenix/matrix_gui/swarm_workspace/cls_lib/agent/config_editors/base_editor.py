from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout

class BaseEditor(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node = node
        self.config = node.config
        self.inputs = {}

        self.setWindowTitle(f"{node.get_name()} Config Editor")
        self.layout = QFormLayout(self)
        self._build_form()

        btns = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.cancel_btn = QPushButton("Cancel")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        self.layout.addRow(btns)

        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self.reject)

    def _build_form(self):
        # Default: simple key/value editors for flat dict configs
        for k, v in self.config.items():
            if isinstance(v, (dict, list)):  # skip complex nested
                continue
            field = QLineEdit(str(v))
            self.layout.addRow(k, field)
            self.inputs[k] = field

    def _save(self):
        for k, widget in self.inputs.items():
            self.node.config[k] = widget.text().strip()
        self.node.mark_dirty()
        self.accept()
