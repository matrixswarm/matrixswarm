from .base_editor import BaseEditor
from .mixin.list_editor_mixin import ListEditorMixin
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)


class GhostWire(BaseEditor, ListEditorMixin):
    """
    GhostWire configuration editor.
    Commander Edition - uses the shared ListEditorMixin for list sections.
    """

    def _build_form(self):
        cfg = self.config

        general_box = QWidget()
        general_layout = QFormLayout(general_box)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(4)

        self.tick_rate = self._spinbox(cfg.get("tick_rate", 5), 1, 3600)
        self.alert_cooldown = self._spinbox(cfg.get("alert_cooldown", 60), 1, 86400)
        self.max_command_hashes = self._spinbox(cfg.get("max_command_hashes", 5000), 100, 100000)
        self.max_session_commands = self._spinbox(cfg.get("max_session_commands", 2000), 100, 100000)
        self.report_to_role = QLineEdit(str(cfg.get("report_to_role", "") or ""))
        self.alert_to_role = QLineEdit(str(cfg.get("alert_to_role") or ""))

        self.install_prompt_command = QCheckBox()
        self.install_prompt_command.setChecked(bool(cfg.get("install_prompt_command", False)))

        ui_cfg = cfg.get("ui", {}) if isinstance(cfg.get("ui"), dict) else {}
        tree_cfg = ui_cfg.get("agent_tree", {}) if isinstance(ui_cfg.get("agent_tree"), dict) else {}
        self.emoji = QLineEdit(str(tree_cfg.get("emoji", "") or ""))

        general_layout.addRow("Tick Rate (sec):", self.tick_rate)
        general_layout.addRow("Alert Cooldown (sec):", self.alert_cooldown)
        general_layout.addRow("Max Command Hashes:", self.max_command_hashes)
        general_layout.addRow("Max Session Commands:", self.max_session_commands)
        general_layout.addRow("Report To Role:", self.report_to_role)
        general_layout.addRow("Alert To Role:", self.alert_to_role)
        general_layout.addRow("Install Prompt Hook:", self.install_prompt_command)
        general_layout.addRow("Agent Tree Emoji:", self.emoji)

        self.layout.addRow(QLabel("General Settings"))
        self.layout.addRow(general_box)

        watch_data = [{"path": p} for p in cfg.get("watch_paths", [])]
        self._build_list_section(
            label="Watch Paths",
            data=watch_data,
            columns=["path"],
            attr_name="watch_paths",
        )

        pattern_data = [{"pattern": p} for p in cfg.get("command_patterns", [])]
        self._build_list_section(
            label="Command Patterns",
            data=pattern_data,
            columns=["pattern"],
            attr_name="command_patterns",
        )

        prompt_data = [{"path": p} for p in cfg.get("prompt_paths", ["/etc/bash.bashrc", "~/.bashrc"])]
        self._build_list_section(
            label="Prompt Hook Files",
            data=prompt_data,
            columns=["path"],
            attr_name="prompt_paths",
        )

    def _spinbox(self, value, minimum, maximum):
        box = QSpinBox()
        box.setRange(minimum, maximum)
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = minimum
        box.setValue(max(minimum, min(maximum, value)))
        return box

    def _column_values(self, attr_name, column):
        values = []
        for row in self._collect_list_data(attr_name):
            if not isinstance(row, dict):
                value = str(row).strip()
            else:
                value = str(row.get(column, "")).strip()
            if value:
                values.append(value)
        return values

    def _save(self):
        watch_paths = self._column_values("watch_paths", "path")
        command_patterns = self._column_values("command_patterns", "pattern")
        prompt_paths = self._column_values("prompt_paths", "path")

        if not watch_paths:
            QMessageBox.warning(self, "Validation Errors", "Add at least one watch path.")
            return

        if not command_patterns:
            QMessageBox.warning(self, "Validation Errors", "Add at least one command pattern.")
            return

        cfg = dict(self.node.config or {})
        cfg.update({
            "tick_rate": self.tick_rate.value(),
            "alert_cooldown": self.alert_cooldown.value(),
            "max_command_hashes": self.max_command_hashes.value(),
            "max_session_commands": self.max_session_commands.value(),
            "report_to_role": self.report_to_role.text().strip() or None,
            "alert_to_role": self.alert_to_role.text().strip() or None,
            "install_prompt_command": self.install_prompt_command.isChecked(),
            "watch_paths": watch_paths,
            "command_patterns": command_patterns,
            "prompt_paths": prompt_paths,
        })

        emoji = self.emoji.text().strip()
        ui_cfg = cfg.setdefault("ui", {})
        if not isinstance(ui_cfg, dict):
            ui_cfg = {}
            cfg["ui"] = ui_cfg
        tree_cfg = ui_cfg.setdefault("agent_tree", {})
        if not isinstance(tree_cfg, dict):
            tree_cfg = {}
            ui_cfg["agent_tree"] = tree_cfg
        tree_cfg["emoji"] = emoji

        if getattr(self.node, "config", None) is None:
            self.node.config = {}
        self.node.config.clear()
        self.node.config.update(cfg)
        self.node.mark_dirty()
        self.accept()