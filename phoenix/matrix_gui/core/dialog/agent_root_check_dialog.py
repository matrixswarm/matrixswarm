"""Keep collecting Clown Car sources until every agent is found or the user cancels."""

from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QTextEdit, QFileDialog, QMessageBox,
)
from matrix_gui.core.class_lib.paths.agent_root_selector import AgentSourceSelection


class AgentRootCheckDialog(QDialog):
    def __init__(self, directive_tree, parent=None, *, selection=None, initial_path=None):
        super().__init__(parent)
        self.setWindowTitle("Clown Car — Locate Agent Sources")
        self.resize(760, 520)
        self.selection = selection if selection is not None else AgentSourceSelection(directive_tree)
        self.selected_path = None
        self.browse_path = str(initial_path or Path.cwd())
        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Select your MatrixSwarm, MatrixOS, or agents folder. If agents are missing, "
            "select their individual folders next. Sources already found are retained."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        layout.addWidget(self.editor)
        self.pick_button = QPushButton("Choose Source Directory…")
        self.pick_button.clicked.connect(self._select_dir)
        cancel = QPushButton("Cancel Deployment")
        cancel.clicked.connect(self.reject)
        layout.addWidget(self.pick_button)
        layout.addWidget(cancel)
        self._show_status()

    def _show_status(self):
        missing = self.selection.missing_agents
        lines = [f"Located {len(self.selection.sources)} of {len(self.selection.required)} agent sources."]
        if missing:
            lines += ["", "Still needed:", *[f"  • {name}" for name in missing]]
        if self.selection.sources:
            lines += ["", "Located:"]
            lines += [f"  {name} ({lang}): {path}" for (name, lang), path in self.selection.sources.items()]
        if self.selection.errors:
            lines += ["", "Source problems:", *self.selection.errors.values()]
        self.editor.setPlainText("\n".join(lines))

    def _select_dir(self):
        missing = self.selection.missing_agents
        title = f"Locate {missing[0]} (or select a shared agents folder)" if missing else "Select Agent Sources"
        directory = QFileDialog.getExistingDirectory(self, title, self.browse_path)
        if not directory:
            return
        self.browse_path = directory
        try:
            complete = self.selection.add_directory(directory)
        except (OSError, ValueError) as exc:
            self._show_status()
            QMessageBox.warning(self, "Source Directory Not Usable", str(exc))
            return
        self._show_status()
        if complete:
            self.selected_path = directory
            self.accept()

    def exec_check(self):
        result = self.exec()
        return self.selected_path if result == QDialog.DialogCode.Accepted else None
