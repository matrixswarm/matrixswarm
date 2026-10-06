"""Edit remote log collector locations without replacing unrelated configuration."""
from copy import deepcopy
import posixpath
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QScrollArea, QWidget, QFormLayout,
)
from .base_editor import BaseEditor
from matrix_gui.modules.railgun.remote_shell import validate_service_log_path


class LogWatcher(BaseEditor):
    def _build_form(self):
        self.resize(1000, 780)
        outer_layout = self.layout
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.layout = QFormLayout(body)
        scroll.setWidget(body)
        outer_layout.addRow(scroll)
        note = QLabel(
            "Enter absolute Linux log FILE paths on the deployment server, one per line. "
            "Ubuntu examples: /var/log/apache2/error.log, /var/log/auth.log, /var/log/syslog. "
            "Use actual files, not directories or wildcard patterns.\n"
            "Rotation adds either .1, .2, ... or dated -YYYYMMDD files; compressed logs are not read. "
            "Paths must pass Railgun's service-log allowlist. Saving does not grant permissions; "
            "deployment applies its configured read-access policy. Save the workspace and redeploy to apply."
        )
        note.setWordWrap(True)
        self.layout.addRow(note)
        self.collectors_table = QTableWidget(0, 5)
        self.collectors_table.setHorizontalHeaderLabels(
            ["Collector", "Server log files (one per line)", "Lines / file", "Rotated files", "Rotation"]
        )
        self.collectors_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.collectors_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.collectors_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.collectors_table.setMinimumHeight(300)
        self.layout.addRow(self.collectors_table)
        collectors = self.config.get("collectors", {})
        if not isinstance(collectors, dict):
            raise ValueError("collectors must be a mapping of collector names to settings")
        for name, cfg in collectors.items():
            self._add_collector(name, cfg)
        buttons = QHBoxLayout()
        add = QPushButton("Add collector")
        remove = QPushButton("Remove selected collector")
        add.clicked.connect(lambda: self._add_collector())
        remove.clicked.connect(self._remove_collector)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        self.layout.addRow(buttons)
        # Retain the existing editor's scalar settings (Oracle, patrol, roles).
        super()._build_form()
        self.layout = outer_layout

    def _add_collector(self, name="", cfg=None):
        cfg = {} if cfg is None else cfg
        if not isinstance(cfg, dict):
            raise ValueError("Each collector must contain a settings object")
        row = self.collectors_table.rowCount()
        self.collectors_table.insertRow(row)
        item = QTableWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, deepcopy(cfg))
        self.collectors_table.setItem(row, 0, item)
        paths = QPlainTextEdit()
        saved_paths = cfg.get("paths", [])
        if not isinstance(saved_paths, list) or any(not isinstance(p, str) for p in saved_paths):
            raise ValueError("Collector paths must be a list of strings")
        paths.setPlainText("\n".join(saved_paths))
        paths.setPlaceholderText("/var/log/apache2/error.log")
        self.collectors_table.setCellWidget(row, 1, paths)
        for column, key, default in [(2, "max_lines", 50), (3, "rotate_depth", 1)]:
            self.collectors_table.setCellWidget(row, column, QLineEdit(str(cfg.get(key, default))))
        rotation = QComboBox()
        rotation.addItems(["dated", "numbered"])
        # Existing deployments used dated rotation when this key was absent.
        self._select_saved_choice(rotation, cfg.get("rotation_style", "dated"))
        self.collectors_table.setCellWidget(row, 4, rotation)
        self.collectors_table.setRowHeight(row, 80)

    def _remove_collector(self):
        row = self.collectors_table.currentRow()
        if row >= 0:
            self.collectors_table.removeRow(row)

    def _save(self):
        collectors = {}
        try:
            if self.collectors_table.rowCount() > 32:
                raise ValueError("Use at most 32 collectors.")
            for row in range(self.collectors_table.rowCount()):
                item = self.collectors_table.item(row, 0)
                name = item.text().strip().lower()
                if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name) or name in collectors:
                    raise ValueError("Use unique collector names (up to 64 letters, digits, underscores or hyphens).")
                paths = [p.strip() for p in self.collectors_table.cellWidget(row, 1).toPlainText().splitlines() if p.strip()]
                if not 1 <= len(paths) <= 16 or any(
                    not posixpath.isabs(p) or p.endswith("/") or "\x00" in p
                    or any(c in p for c in "*?[]") or len(p.encode("utf-8")) > 1024 for p in paths
                ):
                    raise ValueError(f"{name}: enter 1–16 absolute Linux file paths without wildcards (up to 1024 UTF-8 bytes each).")
                paths = [validate_service_log_path(p, f"Log Watcher {name} path") for p in paths]
                max_lines = int(self.collectors_table.cellWidget(row, 2).text())
                depth = int(self.collectors_table.cellWidget(row, 3).text())
                if not 1 <= max_lines <= 5000 or not 0 <= depth <= 30:
                    raise ValueError(f"{name}: lines must be 1–5000 and rotation depth 0–30.")
                style = self._saved_choice(self.collectors_table.cellWidget(row, 4), name)
                if style not in {"dated", "numbered"}:
                    raise ValueError(f"{name}: choose dated or numbered rotation.")
                cfg = deepcopy(item.data(Qt.ItemDataRole.UserRole))
                cfg.update(paths=paths, max_lines=max_lines, rotate_depth=depth, rotation_style=style)
                collectors[name] = cfg
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid Log Watcher configuration", str(exc))
            return
        # Include collectors before BaseEditor emits accepted, but roll back
        # if scalar validation leaves the dialog open. Unexpected failures
        # are handled by BaseEditor's _save_safely transaction.
        before = deepcopy(self.node.config)
        self.node.config["collectors"] = collectors
        super()._save()
        if self.result() != self.DialogCode.Accepted:
            self.node.config.clear()
            self.node.config.update(before)
