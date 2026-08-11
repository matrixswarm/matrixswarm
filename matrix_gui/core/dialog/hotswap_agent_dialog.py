import os
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,
    QComboBox, QPushButton, QFileDialog,
    QMessageBox
)
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class HotswapAgentDialog(QDialog):
    def __init__(self, session_id, bus, tree_data, parent=None):
        super().__init__(parent)

        try:
            self.session_id = session_id
            self.bus = bus
            self.file_path = None
            self.meta = {}

            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("Select Running Agent"))
            self.agent_dropdown = QComboBox()
            self.agent_dropdown.addItems(tree_data)  # universal_ids
            layout.addWidget(self.agent_dropdown)

            self.file_label = QLabel("No file selected")
            btn_pick = QPushButton("📂 Select Source")
            btn_pick.clicked.connect(self.pick_file)
            layout.addWidget(self.file_label)
            layout.addWidget(btn_pick)

            btn_ok = QPushButton("Hotswap")
            btn_ok.clicked.connect(self.deploy)
            layout.addWidget(btn_ok)
        except Exception as e:
            emit_gui_exception_log("HotswapAgentDialog.__init__", e)


    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Source", "", "Python (*.py);;All Files (*)")
        if not path:
            return
        self.file_path = path
        self.file_label.setText(os.path.basename(path))
        self.parse_meta(path)

    def parse_meta(self, path):
        meta_path = os.path.join(os.path.dirname(path), "__AGENT_META__.json")
        if not os.path.exists(meta_path):
            # optional file, just skip silently
            self.meta = {}
            return

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                self.meta = json.load(f)
        except Exception as e:
            # log silently instead of showing a popup
            emit_gui_exception_log("HotswapAgentDialog.parse_meta", e)
            self.meta = {}

    def deploy(self):
        target_uid = self.agent_dropdown.currentText()
        if not self.file_path or not target_uid:
            QMessageBox.warning(self, "Error", "Missing file or agent target.")
            return
        self.accept()
