# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
"""
Module: Agent Root Check Dialog

This module provides a standalone `AgentRootCheckDialog` class for verifying whether all required agent source files
exist in a specified directory. The dialog is designed for use within a PyQt6 application and provides an interactive UI
for selecting and validating the agent root directory.

Classes:
    - AgentRootCheckDialog: A dialog that allows users to check and verify the existence of agent source files.

Dependencies:
    - PyQt6.QtWidgets: Provides the UI components like QDialog, QVBoxLayout, QLabel, QPushButton, QTextEdit, QFileDialog, and QMessageBox.
    - pathlib.Path: Handles file system paths for directory selection.
    - AgentRootSelector: Provides methods for verifying all agent source files in a specified directory.

---

class AgentRootCheckDialog(QDialog):
"""
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QTextEdit, QFileDialog, QMessageBox
)
from matrix_gui.core.class_lib.paths.agent_root_selector import AgentRootSelector

class AgentRootCheckDialog(QDialog):
    """
    Standalone dialog for verifying that all agent sources exist in a chosen directory.
    """

    def __init__(self, directive_tree, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agent Root Verification")
        self.resize(700, 500)
        self.directive_tree = directive_tree
        self.selected_path = None
        self.missing = []
        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select your /agents directory to verify embedded sources:"))
        layout.addWidget(self.editor)

        btn_pick = QPushButton("📁 Choose Directory")
        btn_pick.clicked.connect(self._select_dir)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_pick)
        layout.addWidget(btn_close)

    def _select_dir(self):
        base_dir = QFileDialog.getExistingDirectory(self, "Select Root Agent Directory", str(Path.cwd()))
        if not base_dir:
            return

        try:
            missing = AgentRootSelector.verify_all_sources(self.directive_tree, base_dir)
            if missing:
                msg = (
                    f"The following agents are missing source files under:\n{base_dir}\n\n"
                    + "\n".join(missing)
                )
                self.editor.setPlainText(msg)
                QMessageBox.warning(self, "Missing Sources", msg)
                self.missing = missing
                self.selected_path = None
            else:
                self.editor.setPlainText(f"✅ All agent sources verified under:\n{base_dir}")
                self.selected_path = base_dir
                QMessageBox.information(self, "Verified", "All agent sources found and validated.")
                self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Verification failed:\n{e}")
            self.selected_path = None

    def exec_check(self):
        """
        Run the dialog until a valid path is chosen.
        Returns the verified base path, or None on cancel.
        """
        result = self.exec()
        return self.selected_path if result == QDialog.DialogCode.Accepted else None
