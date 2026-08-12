from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QSpinBox, QCheckBox, QTextEdit,
    QListWidget, QPushButton, QFormLayout, QHBoxLayout, QVBoxLayout,
    QDialog, QMessageBox
)
import json


class RsyncBoy(BaseEditor):
    """
    Unified RsyncBoy editor
    - edits poll interval
    - manages job list
    - edits each job inline via modal dialog
    """

    def _build_form(self):
        cfg = self.config or {}
        self.layout.setSpacing(6)

        # ───────── GENERAL SETTINGS ─────────
        general = QWidget()
        gl = QFormLayout(general)
        gl.setContentsMargins(0, 0, 0, 0)

        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(1, 86400)
        self.poll_interval.setValue(int(cfg.get("poll_interval", 60)))
        gl.addRow("Poll Interval (sec):", self.poll_interval)

        self.layout.addRow(QLabel("🛠️ General"))
        self.layout.addRow(general)

        # ───────── JOBS LIST ─────────
        self.jobs = cfg.get("jobs", [])
        self.jobs_list = QListWidget()
        for j in self.jobs:
            self.jobs_list.addItem(f"{j['id']} | {j.get('factory','')}")

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add Job")
        self.edit_btn = QPushButton("Edit Job")
        self.del_btn = QPushButton("Delete Job")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.del_btn)

        self.layout.addRow(QLabel("Jobs"))
        self.layout.addRow(self.jobs_list)
        self.layout.addRow(btn_row)

        # Connections
        self.add_btn.clicked.connect(self._add_job)
        self.edit_btn.clicked.connect(self._edit_job)
        self.del_btn.clicked.connect(self._delete_job)

    # ──────────────────────────────────────────────
    # JOB OPERATIONS
    # ──────────────────────────────────────────────
    def _add_job(self):
        dlg = JobEditorDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            job = dlg.get_job()
            self.jobs.append(job)
            self.jobs_list.addItem(f"{job['id']} | {job.get('factory','')}")

    def _edit_job(self):
        row = self.jobs_list.currentRow()
        if row < 0:
            return
        dlg = JobEditorDialog(self, self.jobs[row])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.jobs[row] = dlg.get_job()
            self.jobs_list.item(row).setText(f"{self.jobs[row]['id']} | {self.jobs[row].get('factory','')}")

    def _delete_job(self):
        row = self.jobs_list.currentRow()
        if row < 0:
            return
        self.jobs.pop(row)
        self.jobs_list.takeItem(row)

    # ──────────────────────────────────────────────
    # SAVE
    # ──────────────────────────────────────────────
    def _save(self):
        self.node.config["poll_interval"] = int(self.poll_interval.value())
        self.node.config["jobs"] = self.jobs
        self.node.mark_dirty()
        self.accept()


# =====================================================================
# INLINE JOB EDITOR (modal, included in same file)
# =====================================================================
class JobEditorDialog(QDialog):
    """Clean RsyncBoy job editor with explicit fields."""

    def __init__(self, parent=None, job=None):
        super().__init__(parent)
        self.setWindowTitle("Edit RsyncBoy Job")
        self.resize(600, 550)
        self.job = job or self._default_job()

        layout = QFormLayout(self)
        layout.setSpacing(6)

        # ───────── CORE FIELDS ─────────
        self.job_id = QLineEdit(self.job["id"])
        self.enabled = QCheckBox()
        self.enabled.setChecked(bool(self.job.get("enabled", True)))
        self.factory = QLineEdit(self.job.get("factory", "mysql.mysqldump"))

        self.interval = QSpinBox()
        self.interval.setRange(1, 86400)
        self.interval.setValue(int(self.job.get("schedule", {}).get("interval_sec", 86400)))

        self.run_on_boot = QCheckBox()
        self.run_on_boot.setChecked(bool(self.job.get("schedule", {}).get("run_on_boot", False)))

        layout.addRow("Job ID", self.job_id)
        layout.addRow("Enabled", self.enabled)
        layout.addRow("Factory", self.factory)
        layout.addRow("Interval (sec)", self.interval)
        layout.addRow("Run on Boot", self.run_on_boot)

        # ───────── BACKUP CONFIG ─────────
        cfg = self.job.get("config", {})
        self.remote_path = QLineEdit(cfg.get("remote_path", "/srv/backups/mysql/"))
        self.local_tmp = QLineEdit(cfg.get("local_tmp", "/tmp/mysql_dumps"))
        self.dump_flags = QLineEdit(cfg.get("dump_flags", "--single-transaction"))
        self.compress = QCheckBox()
        self.compress.setChecked(bool(cfg.get("compress", True)))
        self.filename_prefix = QLineEdit(cfg.get("filename_prefix", ""))
        self.keep_days = QSpinBox()
        self.keep_days.setRange(0, 90)
        self.keep_days.setValue(int(cfg.get("remote_prune", {}).get("keep_days", 14)))

        layout.addRow(QLabel("— Backup Options —"))
        layout.addRow("Remote Path", self.remote_path)
        layout.addRow("Local Tmp Dir", self.local_tmp)
        layout.addRow("Dump Flags", self.dump_flags)
        layout.addRow("Compress", self.compress)
        layout.addRow("Filename Prefix", self.filename_prefix)
        layout.addRow("Keep Days", self.keep_days)

        # ───────── BUTTONS ─────────
        btns = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addRow(btns)
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    # -----------------------------------
    def _default_job(self):
        return {
            "id": "",
            "enabled": True,
            "factory": "mysql.mysqldump.MySQLDumpJob",
            "schedule": {"interval_sec": 86400, "run_on_boot": False},
            "config": {
                "remote_path": "/srv/backups/mysql/",
                "local_tmp": "/tmp/mysql_dumps",
                "dump_flags": "--single-transaction",
                "compress": True,
                "filename_prefix": "",
                "remote_prune": {"keep_days": 14}
            }
        }

    # -----------------------------------
    def get_job(self):
        return {
            "id": self.job_id.text().strip(),
            "enabled": self.enabled.isChecked(),
            "factory": self.factory.text().strip(),
            "schedule": {
                "interval_sec": int(self.interval.value()),
                "run_on_boot": self.run_on_boot.isChecked()
            },
            "config": {
                "remote_path": self.remote_path.text().strip(),
                "local_tmp": self.local_tmp.text().strip(),
                "dump_flags": self.dump_flags.text().strip(),
                "compress": self.compress.isChecked(),
                "filename_prefix": self.filename_prefix.text().strip(),
                "remote_prune": {"keep_days": int(self.keep_days.value())}
            }
        }
