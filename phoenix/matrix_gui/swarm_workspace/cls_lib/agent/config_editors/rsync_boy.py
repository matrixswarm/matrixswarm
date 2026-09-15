from copy import deepcopy

from .base_editor import BaseEditor
from .rsync_boy_clipboard import (
    FILESYSTEM_FACTORY,
    MYSQL_FACTORY,
    JobClipboardError,
    decode_jobs,
    encode_jobs,
)
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QSpinBox, QCheckBox, QComboBox, QStackedWidget,
    QListWidget, QPushButton, QFormLayout, QHBoxLayout, QVBoxLayout,
    QApplication, QDialog, QMessageBox
)
from matrix_gui.modules.railgun.ssh_support import (
    format_ssh_profile_label,
    load_registry_ssh_profiles,
)


def _profile_choices(profiles=None):
    """Return detached, display-safe profile choices keyed by Registry serial."""
    if profiles is None:
        try:
            profiles = load_registry_ssh_profiles()
        except Exception:
            profiles = {}
    if isinstance(profiles, list):
        profiles = {
            str(item.get("serial", "")): item
            for item in profiles
            if isinstance(item, dict) and item.get("serial")
        }
    if not isinstance(profiles, dict):
        return {}
    return {
        str(serial): dict(profile)
        for serial, profile in profiles.items()
        if serial and isinstance(profile, dict)
    }


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
        self.jobs = deepcopy(cfg.get("jobs", []))
        self.jobs_list = QListWidget()
        self._refresh_jobs_list()

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add Job")
        self.edit_btn = QPushButton("Edit Job")
        self.del_btn = QPushButton("Delete Job")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.del_btn)

        transfer_row = QHBoxLayout()
        self.copy_jobs_btn = QPushButton("📋 Copy All Jobs")
        self.paste_jobs_btn = QPushButton("📥 Paste Jobs")
        transfer_row.addWidget(self.copy_jobs_btn)
        transfer_row.addWidget(self.paste_jobs_btn)
        self.clipboard_status = QLabel("")
        self.clipboard_status.setWordWrap(True)

        self.layout.addRow(QLabel("Jobs"))
        self.layout.addRow(self.jobs_list)
        self.layout.addRow(btn_row)
        self.layout.addRow(transfer_row)
        self.layout.addRow(self.clipboard_status)

        # Connections
        self.add_btn.clicked.connect(self._add_job)
        self.edit_btn.clicked.connect(self._edit_job)
        self.del_btn.clicked.connect(self._delete_job)
        self.copy_jobs_btn.clicked.connect(self._copy_all_jobs)
        self.paste_jobs_btn.clicked.connect(self._paste_jobs)

    # ──────────────────────────────────────────────
    # JOB OPERATIONS
    # ──────────────────────────────────────────────
    def _refresh_jobs_list(self):
        self.jobs_list.clear()
        for job in self.jobs:
            profile = job.get("ssh_profile")
            source = f" | SSH:{str(profile)[-8:]}" if profile else " | SSH:primary"
            self.jobs_list.addItem(
                f"{job.get('id', '')} | {job.get('factory', '')}{source}"
            )

    def _add_job(self):
        dlg = JobEditorDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            job = dlg.get_job()
            self.jobs.append(job)
            self._refresh_jobs_list()

    def _edit_job(self):
        row = self.jobs_list.currentRow()
        if row < 0:
            return
        dlg = JobEditorDialog(self, self.jobs[row])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.jobs[row] = dlg.get_job()
            self._refresh_jobs_list()
            self.jobs_list.setCurrentRow(row)

    def _delete_job(self):
        row = self.jobs_list.currentRow()
        if row < 0:
            return
        self.jobs.pop(row)
        self.jobs_list.takeItem(row)

    def _copy_all_jobs(self):
        try:
            payload = encode_jobs(self.jobs)
        except JobClipboardError as exc:
            QMessageBox.warning(self, "Cannot Copy Jobs", str(exc))
            return
        QApplication.clipboard().setText(payload)
        self.clipboard_status.setText(
            f"Copied {len(self.jobs)} jobs. SSH and MySQL credentials are not included."
        )

    def _paste_jobs(self):
        try:
            imported = decode_jobs(QApplication.clipboard().text())
        except JobClipboardError as exc:
            QMessageBox.warning(self, "Cannot Paste Jobs", str(exc))
            return

        if self.jobs:
            answer = QMessageBox.question(
                self,
                "Replace Existing Jobs?",
                f"Replace the current {len(self.jobs)} jobs with "
                f"{len(imported)} clipboard jobs?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.jobs = imported
        self._refresh_jobs_list()
        self.clipboard_status.setText(
            f"Pasted {len(imported)} jobs — click Save to keep them."
        )

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

    def __init__(self, parent=None, job=None, ssh_profiles=None):
        super().__init__(parent)
        self.setWindowTitle("Edit RsyncBoy Job")
        self.resize(680, 640)
        self.job = job or self._default_job()

        layout = QFormLayout(self)
        layout.setSpacing(6)

        # ───────── CORE FIELDS ─────────
        self.job_id = QLineEdit(self.job["id"])
        self.enabled = QCheckBox()
        self.enabled.setChecked(bool(self.job.get("enabled", True)))
        self.job_type = QComboBox()
        self.job_type.addItem("MySQL timestamped dump", MYSQL_FACTORY)
        self.job_type.addItem("Filesystem timestamped snapshot", FILESYSTEM_FACTORY)

        configured_factory = self.job.get("factory", MYSQL_FACTORY)
        existing_filesystem_job = configured_factory == FILESYSTEM_FACTORY
        selected = self.job_type.findData(configured_factory)
        if selected < 0:
            self.job_type.addItem(f"Legacy: {configured_factory}", configured_factory)
            selected = self.job_type.count() - 1
        self.job_type.setCurrentIndex(selected)

        self.factory = QLineEdit(configured_factory)
        self.factory.setReadOnly(True)

        self.interval = QSpinBox()
        self.interval.setRange(1, 31536000)
        self.interval.setValue(int(self.job.get("schedule", {}).get("interval_sec", 86400)))

        self.run_on_boot = QCheckBox()
        self.run_on_boot.setChecked(bool(self.job.get("schedule", {}).get("run_on_boot", False)))

        self.ssh_profiles = _profile_choices(ssh_profiles)
        self.ssh_profile = QComboBox()
        self.ssh_profile.addItem("Primary SSH profile (legacy/default)", "")
        for serial, profile in sorted(
            self.ssh_profiles.items(),
            key=lambda item: format_ssh_profile_label(item[0], item[1]).lower(),
        ):
            self.ssh_profile.addItem(format_ssh_profile_label(serial, profile), serial)
        configured_profile = str(self.job.get("ssh_profile", "") or "").strip()
        selected_profile = self.ssh_profile.findData(configured_profile)
        if selected_profile < 0 and configured_profile:
            self.ssh_profile.addItem(
                f"Unavailable in this deployment · id:{configured_profile[-8:]}",
                configured_profile,
            )
            selected_profile = self.ssh_profile.count() - 1
        self.ssh_profile.setCurrentIndex(max(0, selected_profile))
        self.ssh_profile_hint = QLabel(
            "The job stores only this Registry ID. Phoenix seals its pinned "
            "credentials into the encrypted deployment."
        )
        self.ssh_profile_hint.setWordWrap(True)

        layout.addRow("Job ID", self.job_id)
        layout.addRow("Enabled", self.enabled)
        layout.addRow("Job Type", self.job_type)
        layout.addRow("Factory", self.factory)
        layout.addRow("Interval (sec)", self.interval)
        layout.addRow("Run on Boot", self.run_on_boot)
        layout.addRow("SSH Profile", self.ssh_profile)
        layout.addRow(self.ssh_profile_hint)

        # ───────── JOB-SPECIFIC CONFIG ─────────
        cfg = self.job.get("config", {})
        mysql_cfg = {} if existing_filesystem_job else cfg
        filesystem_cfg = cfg if existing_filesystem_job else {}
        self.config_pages = QStackedWidget()

        mysql_page = QWidget()
        mysql_layout = QFormLayout(mysql_page)
        self.remote_path = QLineEdit(mysql_cfg.get("remote_path", "/srv/backups/mysql/"))
        self.local_tmp = QLineEdit(mysql_cfg.get("local_tmp", "/tmp/mysql_dumps"))
        self.dump_flags = QLineEdit(mysql_cfg.get("dump_flags", "--single-transaction"))
        self.mysql_via_ssh = QCheckBox()
        self.mysql_via_ssh.setChecked(bool(mysql_cfg.get("mysql_via_ssh", True)))
        self.compress = QCheckBox()
        self.compress.setChecked(bool(mysql_cfg.get("compress", True)))
        self.filename_prefix = QLineEdit(mysql_cfg.get("filename_prefix", ""))
        self.keep_days = QSpinBox()
        self.keep_days.setRange(0, 90)
        self.keep_days.setValue(int(mysql_cfg.get("remote_prune", {}).get("keep_days", 14)))

        mysql_layout.addRow(QLabel("— MySQL Backup Options —"))
        mysql_layout.addRow("Remote Path", self.remote_path)
        mysql_layout.addRow("Local Tmp Dir", self.local_tmp)
        mysql_layout.addRow("Dump Flags", self.dump_flags)
        mysql_layout.addRow("Run MySQL Through SSH", self.mysql_via_ssh)
        mysql_layout.addRow("Compress", self.compress)
        mysql_layout.addRow("Filename Prefix", self.filename_prefix)
        mysql_layout.addRow("Keep Days", self.keep_days)
        self.config_pages.addWidget(mysql_page)

        filesystem_page = QWidget()
        filesystem_layout = QFormLayout(filesystem_page)
        self.source_via_ssh = QCheckBox()
        self.source_via_ssh.setChecked(
            bool(filesystem_cfg.get("source_via_ssh", not existing_filesystem_job))
        )
        self.source_path = QLineEdit(filesystem_cfg.get("source_path", "/sites"))
        self.snapshot_remote_path = QLineEdit(
            filesystem_cfg.get("remote_path", "/backup/snapshots/sites")
        )
        self.snapshot_prefix = QLineEdit(filesystem_cfg.get("snapshot_prefix", "sites"))
        excludes = filesystem_cfg.get("exclude", [])
        if isinstance(excludes, list):
            excludes = ", ".join(str(item) for item in excludes)
        self.exclude = QLineEdit(str(excludes or ""))
        self.exclude.setPlaceholderText("One or more comma-separated rsync patterns")
        self.link_dest = QCheckBox()
        self.link_dest.setChecked(bool(filesystem_cfg.get("link_dest", True)))
        self.preserve_hard_links = QCheckBox()
        self.preserve_hard_links.setChecked(bool(filesystem_cfg.get("preserve_hard_links", True)))
        self.preserve_acls = QCheckBox()
        self.preserve_acls.setChecked(bool(filesystem_cfg.get("preserve_acls", True)))
        self.preserve_xattrs = QCheckBox()
        self.preserve_xattrs.setChecked(bool(filesystem_cfg.get("preserve_xattrs", True)))
        self.snapshot_keep_days = QSpinBox()
        self.snapshot_keep_days.setRange(0, 3650)
        self.snapshot_keep_days.setValue(
            int(filesystem_cfg.get("remote_prune", {}).get("keep_days", 14))
        )

        self.transfer_hint = QLabel()
        self.transfer_hint.setWordWrap(True)
        self.source_path_label = QLabel()
        self.snapshot_root_label = QLabel()

        filesystem_layout.addRow(QLabel("— Filesystem Snapshot Options —"))
        filesystem_layout.addRow("Pull Source Through SSH", self.source_via_ssh)
        filesystem_layout.addRow(self.transfer_hint)
        filesystem_layout.addRow(self.source_path_label, self.source_path)
        filesystem_layout.addRow(self.snapshot_root_label, self.snapshot_remote_path)
        filesystem_layout.addRow("Snapshot Prefix", self.snapshot_prefix)
        filesystem_layout.addRow("Exclude Patterns", self.exclude)
        filesystem_layout.addRow("Hard-link Unchanged Files", self.link_dest)
        filesystem_layout.addRow("Preserve Existing Hard Links", self.preserve_hard_links)
        filesystem_layout.addRow("Preserve ACLs", self.preserve_acls)
        filesystem_layout.addRow("Preserve Extended Attributes", self.preserve_xattrs)
        filesystem_layout.addRow("Keep Days", self.snapshot_keep_days)
        self.config_pages.addWidget(filesystem_page)
        layout.addRow(self.config_pages)

        self.job_type.currentIndexChanged.connect(self._job_type_changed)
        self.source_via_ssh.stateChanged.connect(self._transfer_direction_changed)
        self._transfer_direction_changed()
        self._job_type_changed()

        # ───────── BUTTONS ─────────
        btns = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addRow(btns)
        save_btn.clicked.connect(self._accept_if_valid)
        cancel_btn.clicked.connect(self.reject)

    def _job_type_changed(self):
        factory = self.job_type.currentData()
        self.factory.setText(factory)
        self.config_pages.setCurrentIndex(1 if factory == FILESYSTEM_FACTORY else 0)

    def _transfer_direction_changed(self):
        if self.source_via_ssh.isChecked():
            self.transfer_hint.setText(
                "SSH server → this MatrixOS backup host (recommended for offsite backups)."
            )
            self.source_path_label.setText("SSH Source Path")
            self.snapshot_root_label.setText("Local Snapshot Root")
        else:
            self.transfer_hint.setText("This MatrixOS host → SSH server.")
            self.source_path_label.setText("Local Source Path")
            self.snapshot_root_label.setText("SSH Snapshot Root")

    def _accept_if_valid(self):
        if not self.job_id.text().strip():
            QMessageBox.warning(self, "Missing Job ID", "Job ID is required.")
            return
        if self.job_type.currentData() == FILESYSTEM_FACTORY:
            if not self.source_path.text().strip().startswith("/"):
                QMessageBox.warning(
                    self, "Invalid Source", "Source Path must be an absolute Linux path."
                )
                return
            remote_path = self.snapshot_remote_path.text().strip()
            if not remote_path.startswith("/") or remote_path == "/":
                QMessageBox.warning(
                    self,
                    "Invalid Destination",
                    "Snapshot Root must be an absolute, non-root Linux path.",
                )
                return
        self.accept()

    # -----------------------------------
    def _default_job(self):
        return {
            "id": "",
            "enabled": True,
            "factory": MYSQL_FACTORY,
            "schedule": {"interval_sec": 86400, "run_on_boot": False},
            "config": {
                "remote_path": "/srv/backups/mysql/",
                "local_tmp": "/tmp/mysql_dumps",
                "dump_flags": "--single-transaction",
                "mysql_via_ssh": True,
                "compress": True,
                "filename_prefix": "",
                "remote_prune": {"keep_days": 14}
            }
        }

    # -----------------------------------
    def get_job(self):
        factory = self.job_type.currentData()
        if factory == FILESYSTEM_FACTORY:
            config = {
                "source_via_ssh": self.source_via_ssh.isChecked(),
                "source_path": self.source_path.text().strip(),
                "remote_path": self.snapshot_remote_path.text().strip(),
                "snapshot_prefix": self.snapshot_prefix.text().strip(),
                "exclude": [
                    item.strip()
                    for item in self.exclude.text().split(",")
                    if item.strip()
                ],
                "link_dest": self.link_dest.isChecked(),
                "preserve_hard_links": self.preserve_hard_links.isChecked(),
                "preserve_acls": self.preserve_acls.isChecked(),
                "preserve_xattrs": self.preserve_xattrs.isChecked(),
                "remote_prune": {"keep_days": int(self.snapshot_keep_days.value())},
            }
        else:
            config = {
                "remote_path": self.remote_path.text().strip(),
                "local_tmp": self.local_tmp.text().strip(),
                "dump_flags": self.dump_flags.text().strip(),
                "mysql_via_ssh": self.mysql_via_ssh.isChecked(),
                "compress": self.compress.isChecked(),
                "filename_prefix": self.filename_prefix.text().strip(),
                "remote_prune": {"keep_days": int(self.keep_days.value())}
            }

        result = {
            "id": self.job_id.text().strip(),
            "enabled": self.enabled.isChecked(),
            "factory": factory,
            "schedule": {
                "interval_sec": int(self.interval.value()),
                "run_on_boot": self.run_on_boot.isChecked()
            },
            "config": config,
        }
        ssh_profile = str(self.ssh_profile.currentData() or "").strip()
        if ssh_profile:
            result["ssh_profile"] = ssh_profile
        return result
