"""Deployment configuration and explicit upgrade for existing Log Health nodes."""
from copy import deepcopy
import json
import posixpath

from PyQt6.QtWidgets import QCheckBox, QLabel, QLineEdit, QMessageBox, QPlainTextEdit
from .base_editor import BaseEditor


PANEL = "log_health.log_health"
ROUTES = ["hive.log_health.snapshot@cmd_snapshot", "hive.log_health.analyze@cmd_analyze"]


class LogHealth(BaseEditor):
    def _build_form(self):
        self.path = QLineEdit(str(self.config.get("log_path", "")))
        self.service = QLineEdit(str(self.config.get("service_name", "generic.log")))
        self.report = QLineEdit(str(self.config.get("report_to_role", "hive.forensics.data_feed")))
        self.oracle = QLineEdit(str(self.config.get("oracle_role", "hive.oracle")))
        self.layout.addRow("Server log file:", self.path)
        self.layout.addRow("Service name:", self.service)
        self.layout.addRow("Forensic report role:", self.report)
        self.layout.addRow("Oracle role (one agent):", self.oracle)
        self.monitor = QCheckBox("Enable Log Monitor and Ask Oracle")
        self.monitor.setChecked(PANEL in self.config.get("ui", {}).get("panel", []))
        self.layout.addRow(self.monitor)
        note = QLabel(
            "Enabling adds this agent's signed panel routes and packet-signing constraint. "
            "Save, resolve constraints and redeploy to activate it on an existing agent.\n"
            "Use the real absolute Linux file path (no final symlink). For Ubuntu Apache this is "
            "usually /var/log/apache2/error.log. This editor does not grant file permissions.\n"
            "Oracle is requested manually from the panel, using an excerpt you can review first."
        )
        note.setWordWrap(True)
        self.layout.addRow(note)
        self.rules = QPlainTextEdit()
        self.rules.setPlainText(json.dumps(self.config.get("severity_rules", {
            "CRITICAL": ["fatal", "critical", "segfault"],
            "WARNING": ["error", "warn", "denied", "failed"]}), indent=2))
        self.rules.setMaximumHeight(180)
        self.layout.addRow("Severity keywords (JSON):", self.rules)

    def _save(self):
        path, service = self.path.text().strip(), self.service.text().strip()
        report, oracle = self.report.text().strip(), self.oracle.text().strip()
        try:
            if not posixpath.isabs(path) or "\x00" in path or len(path.encode("utf-8")) > 1024:
                raise ValueError("Enter an absolute Linux log path of at most 1024 UTF-8 bytes.")
            if not service or len(service) > 160 or not report or not oracle:
                raise ValueError("Enter a service name (up to 160 characters) and both service roles.")
            rules = json.loads(self.rules.toPlainText())
            if not isinstance(rules, dict) or any(
                    level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
                    or not isinstance(words, list)
                    or any(not isinstance(word, str) or not word for word in words)
                    for level, words in rules.items()):
                raise ValueError("Use severity names CRITICAL, ERROR, WARNING, INFO or DEBUG, with lists of nonempty keywords.")
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid Log Health configuration", str(exc))
            return
        updated = deepcopy(self.node.config)
        updated.update(log_path=path, service_name=service, report_to_role=report,
                       oracle_role=oracle, severity_rules=rules)
        ui = updated.setdefault("ui", {})
        panels = [panel for panel in ui.get("panel", []) if panel != PANEL]
        routes = []
        # Preserve all unrelated roles and service metadata.
        for entry in updated.get("service-manager", []):
            entry["role"] = [role for role in entry.get("role", []) if role not in ROUTES]
            if entry != {"role": []}:
                routes.append(entry)
        if self.monitor.isChecked():
            panels.append(PANEL)
            routes.append({"role": list(ROUTES)})
        ui["panel"] = panels
        updated["service-manager"] = routes
        before_constraints = deepcopy(self.node.constraints)
        try:
            if self.monitor.isChecked():
                signing = next((item for item in self.node.constraints
                                if item.get("class") == "packet_signing"), None)
                if signing is None:
                    self.node.add_constraint("packet_signing", {"in": True, "out": True})
                else:
                    signing.setdefault("raw", {}).update({"in": True, "out": True})
                    signing["required"] = True
            self.node.config.clear()
            self.node.config.update(updated)
            self.node.mark_dirty()
            self.accept()
        except Exception:
            self.node.constraints = before_constraints
            raise
