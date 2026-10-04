"""Operator-owned assignment selection and non-blocking approval prompts."""
from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QVBoxLayout,
)


class AssignmentDialog(QDialog):
    def __init__(self, deployments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose terminal assignment")
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        label = QLabel("Select deployments the terminal may use for this session.\n"
                       "Inspection is available immediately. Connections, restarts, and\n"
                       "permitted saved-setting changes require your approval each time.")
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        self.deployments = QListWidget()
        for deployment in deployments:
            item = QListWidgetItem(f"{deployment['label']} [{deployment['id']}]")
            item.setData(Qt.ItemDataRole.UserRole, deployment["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.deployments.addItem(item)
        layout.addWidget(self.deployments)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setEnabled(False)
        self.deployments.itemChanged.connect(lambda _: self.ok_button.setEnabled(bool(self.selected_ids())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_ids(self):
        return [self.deployments.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.deployments.count())
                if self.deployments.item(i).checkState() == Qt.CheckState.Checked]


class ApprovalPresenter(QObject):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.parent_window = parent
        self.prompt = None
        self.request = None
        self.resolving = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(400)

    def poll(self):
        if self.resolving:
            return
        pending = self.backend.pending_approval()
        if self.prompt is not None:
            if pending is None or pending["assignment_id"] != self.request["assignment_id"] or pending["request_id"] != self.request["request_id"]:
                self.close_prompt()
            return
        if pending is None:
            return
        self.request = pending
        box = QMessageBox(self.parent_window)
        box.setWindowTitle("Approve terminal action")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(pending["text"])
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setEscapeButton(QMessageBox.StandardButton.No)
        box.finished.connect(lambda result: self._finished(box, pending, result))
        self.prompt = box
        box.open()

    def _finished(self, box, pending, result):
        if box is not self.prompt:
            return
        self.prompt = self.request = None
        box.deleteLater()
        self.resolving = True
        try:
            self.backend.resolve_action(pending["request_id"], result == QMessageBox.StandardButton.Yes,
                                        pending["assignment_id"])
        finally:
            self.resolving = False

    def close_prompt(self):
        box = self.prompt
        self.prompt = self.request = None
        if box is not None:
            box.close()
            box.deleteLater()
