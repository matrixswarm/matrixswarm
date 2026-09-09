from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from .base_editor import BaseEditor
from .mixin.list_editor_mixin import ListEditorMixin


class SiteSentinel(BaseEditor, ListEditorMixin):
    def _spin(self, value, low, high):
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.setValue(int(value))
        return widget

    def _double(self, value, low, high, decimals=2):
        widget = QDoubleSpinBox()
        widget.setRange(low, high)
        widget.setDecimals(decimals)
        widget.setValue(float(value))
        return widget

    def _build_form(self):
        cfg = self.config
        general = QWidget()
        form = QFormLayout(general)
        form.setContentsMargins(0, 0, 0, 0)

        self.interval = self._spin(cfg.get("interval_sec", 30), 5, 86400)
        self.timeout = self._spin(cfg.get("request_timeout_sec", 8), 1, 120)
        self.failure_threshold = self._spin(cfg.get("failure_threshold", 3), 1, 20)
        self.recovery_threshold = self._spin(cfg.get("recovery_threshold", 2), 1, 20)
        self.latency_warning = self._spin(cfg.get("latency_warning_ms", 2500), 100, 120000)
        self.tls_warning = self._spin(cfg.get("tls_warning_days", 21), 1, 365)
        self.check_assets = QCheckBox("Verify linked CSS, JavaScript, and images")
        self.check_assets.setChecked(bool(cfg.get("check_assets", True)))
        self.max_assets = self._spin(cfg.get("max_assets", 8), 0, 25)
        self.log_every = self._spin(cfg.get("log_every", 300), 30, 86400)
        self.report_role = QLineEdit(cfg.get("report_to_role", "hive.forensics.data_feed"))

        form.addRow("Check Interval (sec):", self.interval)
        form.addRow("Request Timeout (sec):", self.timeout)
        form.addRow("Failure Confirmations:", self.failure_threshold)
        form.addRow("Recovery Confirmations:", self.recovery_threshold)
        form.addRow("Latency Warning (ms):", self.latency_warning)
        form.addRow("TLS Warning (days):", self.tls_warning)
        form.addRow(self.check_assets)
        form.addRow("Maximum Assets Per Check:", self.max_assets)
        form.addRow("Summary Log Interval (sec):", self.log_every)
        form.addRow("Forensic Report Role:", self.report_role)
        self.layout.addRow(QLabel("🛰️ Site Health and Presentation"))
        self.layout.addRow(general)

        targets = []
        for target in cfg.get("targets", []):
            if isinstance(target, dict):
                targets.append({
                    "url": target.get("url", ""),
                    "origin_url": target.get("origin_url", ""),
                    "host_header": target.get("host_header", ""),
                    "expect": target.get("expect", ""),
                    "note": target.get("note", ""),
                })
        self._build_list_section(
            label="🌐 Public and Origin Targets",
            data=targets,
            columns=["url", "origin_url", "host_header", "expect", "note"],
            attr_name="targets",
        )

        traffic_cfg = cfg.get("traffic", {}) or {}
        traffic = QWidget()
        traffic_form = QFormLayout(traffic)
        traffic_form.setContentsMargins(0, 0, 0, 0)
        self.traffic_enabled = QCheckBox("Analyze web traffic and abusive clients")
        self.traffic_enabled.setChecked(bool(traffic_cfg.get("enabled", True)))
        self.access_logs = QPlainTextEdit()
        self.access_logs.setPlainText("\n".join(traffic_cfg.get("access_logs", [])))
        self.access_logs.setMaximumHeight(80)
        self.ignored_ips = QPlainTextEdit()
        self.ignored_ips.setPlainText("\n".join(traffic_cfg.get("ignored_ips", [])))
        self.ignored_ips.setMaximumHeight(65)
        self.prefer_forwarded_ip = QCheckBox(
            "Prefer CF-Connecting-IP/X-Forwarded-For when present in JSON or appended logs"
        )
        self.prefer_forwarded_ip.setChecked(bool(traffic_cfg.get("prefer_forwarded_ip", True)))
        self.traffic_window = self._spin(traffic_cfg.get("window_sec", 60), 10, 3600)
        self.top_n_ips = self._spin(traffic_cfg.get("top_n_ips", 10), 1, 50)
        self.per_ip_warning = self._double(traffic_cfg.get("per_ip_warning_rpm", 120), 1, 100000, 1)
        self.per_ip_critical = self._double(traffic_cfg.get("per_ip_critical_rpm", 300), 1, 100000, 1)
        self.total_warning = self._double(traffic_cfg.get("total_warning_rpm", 600), 1, 1000000, 1)
        self.total_critical = self._double(traffic_cfg.get("total_critical_rpm", 1500), 1, 1000000, 1)
        self.unique_paths = self._spin(traffic_cfg.get("unique_path_warning", 80), 1, 100000)
        self.error_ratio = self._double(traffic_cfg.get("error_ratio_warning", 0.35), 0, 1, 2)

        traffic_form.addRow(self.traffic_enabled)
        traffic_form.addRow("Access Logs (one per line):", self.access_logs)
        traffic_form.addRow("Window (sec):", self.traffic_window)
        traffic_form.addRow("Top IPs Retained:", self.top_n_ips)
        traffic_form.addRow("Per-IP Warning (requests/min):", self.per_ip_warning)
        traffic_form.addRow("Per-IP Critical (requests/min):", self.per_ip_critical)
        traffic_form.addRow("Total Warning (requests/min):", self.total_warning)
        traffic_form.addRow("Total Critical (requests/min):", self.total_critical)
        traffic_form.addRow("Crawler Unique-Path Threshold:", self.unique_paths)
        traffic_form.addRow("Error-Ratio Threshold:", self.error_ratio)
        traffic_form.addRow(self.prefer_forwarded_ip)
        traffic_form.addRow("Ignored IPs (one per line):", self.ignored_ips)
        self.layout.addRow(QLabel("📈 Load and Scraper Detection"))
        self.layout.addRow(traffic)

        load_cfg = cfg.get("load", {}) or {}
        load = QWidget()
        load_form = QFormLayout(load)
        load_form.setContentsMargins(0, 0, 0, 0)
        self.cpu_warning = self._double(load_cfg.get("cpu_warning_pct", 80), 1, 100, 1)
        self.cpu_critical = self._double(load_cfg.get("cpu_critical_pct", 95), 1, 100, 1)
        self.memory_warning = self._double(load_cfg.get("memory_warning_pct", 90), 1, 100, 1)
        self.memory_critical = self._double(load_cfg.get("memory_critical_pct", 97), 1, 100, 1)
        self.load_per_cpu = self._double(load_cfg.get("load_warning_per_cpu", 1.5), 0.1, 100, 2)
        self.load_critical_per_cpu = self._double(load_cfg.get("load_critical_per_cpu", 3.0), 0.1, 100, 2)
        load_form.addRow("CPU Warning (%):", self.cpu_warning)
        load_form.addRow("CPU Critical (%):", self.cpu_critical)
        load_form.addRow("Memory Warning (%):", self.memory_warning)
        load_form.addRow("Memory Critical (%):", self.memory_critical)
        load_form.addRow("Load/CPU Warning:", self.load_per_cpu)
        load_form.addRow("Load/CPU Critical:", self.load_critical_per_cpu)
        self.layout.addRow(QLabel("🖥️ Server Pressure"))
        self.layout.addRow(load)

    @staticmethod
    def _lines(widget):
        return [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]

    def _save(self):
        targets = []
        for target in self._collect_list_data("targets"):
            url = target.get("url", "").strip()
            if not url:
                continue
            targets.append({key: target.get(key, "").strip() for key in (
                "url", "origin_url", "host_header", "expect", "note"
            )})
        self.node.config.update({
            "interval_sec": self.interval.value(),
            "request_timeout_sec": self.timeout.value(),
            "failure_threshold": self.failure_threshold.value(),
            "recovery_threshold": self.recovery_threshold.value(),
            "latency_warning_ms": self.latency_warning.value(),
            "tls_warning_days": self.tls_warning.value(),
            "check_assets": self.check_assets.isChecked(),
            "max_assets": self.max_assets.value(),
            "log_every": self.log_every.value(),
            "report_to_role": self.report_role.text().strip(),
            "targets": targets,
            "traffic": {
                "enabled": self.traffic_enabled.isChecked(),
                "access_logs": self._lines(self.access_logs),
                "window_sec": self.traffic_window.value(),
                "top_n_ips": self.top_n_ips.value(),
                "ignored_ips": self._lines(self.ignored_ips),
                "prefer_forwarded_ip": self.prefer_forwarded_ip.isChecked(),
                "per_ip_warning_rpm": self.per_ip_warning.value(),
                "per_ip_critical_rpm": self.per_ip_critical.value(),
                "total_warning_rpm": self.total_warning.value(),
                "total_critical_rpm": self.total_critical.value(),
                "unique_path_warning": self.unique_paths.value(),
                "error_ratio_warning": self.error_ratio.value(),
            },
            "load": {
                "cpu_warning_pct": self.cpu_warning.value(),
                "cpu_critical_pct": self.cpu_critical.value(),
                "memory_warning_pct": self.memory_warning.value(),
                "memory_critical_pct": self.memory_critical.value(),
                "load_warning_per_cpu": self.load_per_cpu.value(),
                "load_critical_per_cpu": self.load_critical_per_cpu.value(),
            },
        })
        self.node.mark_dirty()
        self.accept()
