# Commander & ChatGPT – Victory Always Edition
# Uptime Sentinel Config Editor
# Clean, simple, powerful.

from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QSpinBox, QFormLayout, QCheckBox
)
from .base_editor import BaseEditor
from .mixin.list_editor_mixin import ListEditorMixin
from .mixin.service_roles_mixin import ServiceRolesMixin


class UptimeSentinel(BaseEditor, ListEditorMixin, ServiceRolesMixin):

    def _build_form(self):
        cfg = self.config

        # ---------------------------------------------
        # GENERAL SETTINGS
        # ---------------------------------------------
        general_box = QWidget()
        gl = QFormLayout(general_box)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(4)

        # interval
        self.interval = QSpinBox()
        self.interval.setRange(5, 86400)
        self.interval.setValue(int(cfg.get("interval_sec", 30)))

        # cooldown
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 86400)
        self.cooldown.setValue(int(cfg.get("cooldown", 120)))

        # alert enabled toggle
        self.alert_enabled = QCheckBox("Enable alerts")
        self.alert_enabled.setChecked(bool(cfg.get("alert_enabled", 0)))

        # --- Logging behaviour ---
        self.log_every = QSpinBox()
        self.log_every.setRange(30, 86400)
        self.log_every.setValue(int(cfg.get("log_every", 300)))

        self.only_log_state_changes = QCheckBox("Log only when state changes")
        self.only_log_state_changes.setChecked(bool(cfg.get("only_log_state_changes", False)))

        gl.addRow("Summary Log Interval (sec):", self.log_every)
        gl.addRow(self.only_log_state_changes)

        # alert role
        self.alert_role = QLineEdit(cfg.get("alert_to_role", "mailman-1"))

        gl.addRow("Interval (sec):", self.interval)
        gl.addRow("Cooldown (sec):", self.cooldown)
        gl.addRow("Alerts Enabled:", self.alert_enabled)
        gl.addRow("Alert To Role:", self.alert_role)

        self.layout.addRow(QLabel("🟢 Uptime Sentinel Settings"))
        self.layout.addRow(general_box)

        # ---------------------------------------------
        # TARGETS (URL, note, expect)
        # ---------------------------------------------
        targets = cfg.get("targets", [])
        # Normalize targets (list of dicts)
        normalized = []
        for t in targets:
            if isinstance(t, str):
                normalized.append({"url": t, "note": "", "expect": ""})
            else:
                normalized.append({
                    "url": t.get("url", ""),
                    "note": t.get("note", ""),
                    "expect": t.get("expect", "")
                })

        self._build_list_section(
            label="🌐 Endpoints",
            data=normalized,
            columns=[
                "url",
                "note",
                "expect"
            ],
            attr_name="targets"
        )

        # ---------------------------------------------
        # SERVICE-MANAGER ROLES (optional)
        # ---------------------------------------------
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="uptime_sentinel.status@cmd_status")

    # ---------------------------------------------
    # SAVE CONFIG
    # ---------------------------------------------
    def _save(self):
        roles = self._collect_roles()

        targets = self._collect_list_data("targets")

        # ensure URLs are non-empty
        clean_targets = []
        for t in targets:
            url = t.get("url", "").strip()
            if not url:
                continue
            clean_targets.append({
                "url": url,
                "note": t.get("note", "").strip(),
                "expect": t.get("expect", "").strip()
            })

        self.node.config.update({
            "interval_sec": int(self.interval.value()),
            "cooldown": int(self.cooldown.value()),
            "alert_to_role": self.alert_role.text().strip(),
            "log_every": int(self.log_every.value()),
            "alert_enabled": self.alert_enabled.isChecked(),
            "only_log_state_changes": self.only_log_state_changes.isChecked(),
            "targets": clean_targets,
            "service-manager": [{"role": roles}],
        })

        self.node.mark_dirty()
        self.accept()
