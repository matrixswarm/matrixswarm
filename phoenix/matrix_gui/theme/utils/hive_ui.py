from PyQt6.QtWidgets import QLabel, QGroupBox, QVBoxLayout
from PyQt6.QtCore import Qt

# Keep the dashboard and live-session content on the same horizontal grid.
COCKPIT_CONTENT_GUTTER = 6


class StatusLabel(QLabel):
    def __init__(self, text="—"):
        super().__init__(text)
        self.setObjectName("status")  # picks up QLabel.status from QSS
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

class HiveGroup(QGroupBox):
    def __init__(self, title):
        super().__init__(title)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(6, 6, 6, 6)
        self.layout().setSpacing(4)

    def add_widget(self, widget):
        self.layout().addWidget(widget)
        return widget
