"""Typed settings for the SSH reply outbox and Phoenix receive poller."""

from PyQt6.QtWidgets import QLabel, QSpinBox
from .matrix_ssh import MatrixSsh


class MatrixSshEgress(MatrixSsh):
    def _build_form(self):
        super()._build_form()
        self.setWindowTitle("Matrix SSH Egress Settings")
        self.ssh_mode.setItemText(0, "One-shot (new SSH connection per poll)")
        self.poll_interval.setMaximum(30)
        self.layout.addRow(QLabel("Replies remain private to each authenticated Phoenix session."))
        self._egress_fields = {}
        for key, label, default, low, high in (
            ("packet_ttl", "Reply Expiry (seconds):", 300, 30, 300),
            ("session_timeout", "Session Timeout (seconds):", 180, 60, 900),
            ("max_pending_packets", "Maximum Queued Replies:", 1024, 32, 4096),
        ):
            widget = QSpinBox()
            widget.setRange(low, high)
            widget.setValue(int(self.config.get(key, default)))
            self.layout.addRow(label, widget)
            self._egress_fields[key] = widget

    def _save(self):
        self.node.config.update({key: widget.value() for key, widget in self._egress_fields.items()})
        # Saved workspaces predate the panel metadata. Attach this agent's
        # panel on Save while preserving any other operator-selected panels.
        ui = self.node.config.setdefault("ui", {})
        panels = ui.setdefault("panel", [])
        panel = "matrix_ssh_egress.matrix_ssh_egress"
        if panel not in panels:
            panels.append(panel)
        super()._save()
