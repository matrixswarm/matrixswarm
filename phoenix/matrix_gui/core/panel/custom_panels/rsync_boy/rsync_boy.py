"""Live, agent-scoped RsyncBoy job administration panel."""

from copy import deepcopy
from datetime import datetime
import time
import uuid

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import (
    PhoenixPanelInterface,
)
from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.rsync_boy import (
    JobEditorDialog,
)


class RsyncBoy(PhoenixPanelInterface):
    cache_panel = True
    received = pyqtSignal(object)

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.agent_uid = (node or {}).get("universal_id")
        self.token = uuid.uuid4().hex
        self.jobs = []
        self.runtime = {}
        self.revision = None
        self.dirty = False
        self.pending = None
        self._signals_connected = False
        self.setLayout(self._build_ui())
        self.received.connect(self._receive)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(3000)
        self.refresh_timer.timeout.connect(self._refresh_running_jobs)
        self.refresh_timer.timeout.connect(self._tick)
        self._timers.append(self.refresh_timer)
        self._set_busy(False)

    def _build_ui(self):
        layout = QVBoxLayout()
        heading = QHBoxLayout()
        heading.addWidget(QLabel("💾 RsyncBoy Jobs · Live MatrixOS"))
        heading.addStretch()
        heading.addWidget(QLabel("Scheduler poll (seconds):"))
        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(1, 86400)
        self.poll_interval.setValue(60)
        self.poll_interval.valueChanged.connect(self._mark_dirty)
        heading.addWidget(self.poll_interval)
        layout.addLayout(heading)

        help_text = QLabel(
            "Jobs shown here are loaded from the selected live RsyncBoy agent. "
            "Save Changes validates and encrypts the complete schedule on MatrixOS. "
            "Execute Now runs one saved job immediately, including a disabled job."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.status_label = QLabel("Open this panel to load the server schedule.")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Job", "Type", "Schedule", "Last success", "State", "Actions"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        controls = QHBoxLayout()
        self.new_btn = QPushButton("＋ New Job")
        self.reload_btn = QPushButton("Reload Server")
        self.save_btn = QPushButton("Save Changes")
        self.new_btn.clicked.connect(self._new_job)
        self.reload_btn.clicked.connect(self._reload)
        self.save_btn.clicked.connect(self._save)
        controls.addWidget(self.new_btn)
        controls.addWidget(self.reload_btn)
        controls.addWidget(self.save_btn)
        controls.addStretch()
        layout.addLayout(controls)
        return layout

    @staticmethod
    def _factory_label(factory):
        if factory == "mysql.mysqldump.MySQLDumpJob":
            return "MySQL dump"
        if factory == "filesystem.rsync_snapshot.RsyncSnapshotJob":
            return "Filesystem snapshot"
        return str(factory)

    @staticmethod
    def _time_label(value):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "Never"
        try:
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            return "Unknown"

    def _render(self):
        self.table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            job_id = job.get("id", "")
            status = self.runtime.get(job_id, {})
            interval = job.get("schedule", {}).get("interval_sec", 0)
            schedule = f"Every {interval}s"
            if job.get("schedule", {}).get("run_on_boot"):
                schedule += " · boot"
            state = "RUNNING" if status.get("running") else (
                "Enabled" if job.get("enabled") else "Disabled"
            )
            values = (
                job_id,
                self._factory_label(job.get("factory")),
                schedule,
                self._time_label(status.get("last_success")),
                state,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 4 and status.get("running"):
                    item.setForeground(Qt.GlobalColor.green)
                self.table.setItem(row, column, item)

            actions = QHBoxLayout()
            actions.setContentsMargins(0, 0, 0, 0)
            edit_btn = QPushButton("Edit")
            run_btn = QPushButton("▶ Execute Now")
            delete_btn = QPushButton("Delete")
            edit_btn.clicked.connect(lambda _=False, jid=job_id: self._edit_job(jid))
            run_btn.clicked.connect(lambda _=False, jid=job_id: self._execute_job(jid))
            delete_btn.clicked.connect(lambda _=False, jid=job_id: self._delete_job(jid))
            run_btn.setEnabled(
                self.revision is not None
                and not self.pending
                and not self.dirty
                and not status.get("running")
            )
            edit_btn.setEnabled(not self.pending)
            delete_btn.setEnabled(not self.pending)
            actions.addWidget(edit_btn)
            actions.addWidget(run_btn)
            actions.addWidget(delete_btn)
            actions.addStretch()
            action_host = QWidget()
            action_host.setLayout(actions)
            self.table.setCellWidget(row, 5, action_host)
        self.table.resizeRowsToContents()

    def _set_busy(self, busy):
        ready = self.revision is not None and not busy
        self.table.setEnabled(not busy)
        self.poll_interval.setEnabled(ready)
        self.new_btn.setEnabled(ready)
        self.save_btn.setEnabled(ready and self.dirty)
        self.reload_btn.setEnabled(not busy)
        self._render()

    def _mark_dirty(self, *_):
        if self.revision is None or self.pending:
            return
        self.dirty = True
        self.status_label.setText(
            "Unsaved draft — Save Changes applies this complete schedule to the live agent."
        )
        self._set_busy(False)

    def _new_job(self):
        dialog = JobEditorDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            candidate = dialog.get_job()
            if any(job.get("id") == candidate["id"] for job in self.jobs):
                QMessageBox.warning(self, "Duplicate Job", "Job IDs must be unique.")
                return
            self.jobs.append(candidate)
            self._mark_dirty()

    def _edit_job(self, job_id):
        index = next((i for i, job in enumerate(self.jobs) if job.get("id") == job_id), -1)
        if index < 0:
            return
        dialog = JobEditorDialog(self, deepcopy(self.jobs[index]))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            candidate = dialog.get_job()
            if any(
                i != index and job.get("id") == candidate["id"]
                for i, job in enumerate(self.jobs)
            ):
                QMessageBox.warning(self, "Duplicate Job", "Job IDs must be unique.")
                return
            self.jobs[index] = candidate
            self._mark_dirty()

    def _delete_job(self, job_id):
        if QMessageBox.question(
            self,
            "Delete Job",
            f"Delete '{job_id}' from the live schedule when changes are saved?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]
        self._mark_dirty()

    def _send(self, service, **extra):
        request_id = extra.pop("request_id", uuid.uuid4().hex)
        payload = dict(
            extra,
            target_universal_id=self.agent_uid,
            session_id=self.session_id,
            token=self.token,
            request_id=request_id,
        )
        packet = Packet()
        packet.set_data(
            {
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "hive.rsync_boy." + service,
                    "payload": payload,
                },
            }
        )
        self.bus.emit(
            "outbound.message",
            session_id=self.session_id,
            channel="outgoing.command",
            packet=packet,
        )
        return request_id

    def _request(self, operation, **extra):
        if self.pending:
            return
        request_id = uuid.uuid4().hex
        self.pending = (request_id, operation, time.monotonic())
        self._set_busy(True)
        messages = {
            "get_jobs": "Loading jobs from RsyncBoy…",
            "update_jobs": "Validating and saving encrypted job state…",
            "execute_job": "Starting the selected job…",
        }
        self.status_label.setText(messages[operation])
        try:
            self._send(operation, request_id=request_id, **extra)
        except Exception:
            self.pending = None
            self._set_busy(False)
            self.status_label.setText("Request could not be sent. Your draft has been kept.")

    def _reload(self):
        if self.dirty and QMessageBox.question(
            self,
            "Reload Server Jobs",
            "Discard this unsaved draft and reload the live agent schedule?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._request("get_jobs")

    def _save(self):
        if self.revision is None or not self.dirty:
            return
        self._request(
            "update_jobs",
            revision=self.revision,
            poll_interval=int(self.poll_interval.value()),
            jobs=deepcopy(self.jobs),
        )

    def _execute_job(self, job_id):
        if self.dirty:
            self.status_label.setText("Save Changes before executing a job.")
            return
        self._request("execute_job", job_id=job_id)

    def _handle_jobs(self, session_id, channel=None, source=None, payload=None, **_):
        if session_id != self.session_id or not isinstance(payload, dict):
            return
        content = payload.get("content")
        if (
            not isinstance(content, dict)
            or content.get("token") != self.token
            or content.get("agent_uid") != self.agent_uid
        ):
            return
        self.received.emit(content)

    def _receive(self, content):
        if (
            not self._signals_connected
            or not self.pending
            or content.get("request_id") != self.pending[0]
        ):
            return
        operation = self.pending[1]
        self.pending = None
        if not content.get("ok"):
            self._set_busy(False)
            self.status_label.setText(
                "Request rejected: " + str(content.get("error", "unknown error"))
            )
            return
        jobs = content.get("jobs")
        revision = content.get("revision")
        runtime = content.get("runtime", {})
        if not isinstance(jobs, list) or type(revision) is not int or not isinstance(runtime, dict):
            self._set_busy(False)
            self.status_label.setText("Invalid agent response. Reload to confirm server state.")
            return
        self.jobs = deepcopy(jobs)
        self.runtime = runtime
        self.revision = revision
        self.poll_interval.blockSignals(True)
        self.poll_interval.setValue(int(content.get("poll_interval", 60)))
        self.poll_interval.blockSignals(False)
        self.dirty = False
        self._set_busy(False)
        if operation == "execute_job":
            self.status_label.setText(str(content.get("message", "Job started.")))
        else:
            action = "Saved" if operation == "update_jobs" else "Loaded"
            self.status_label.setText(
                f"{action} {len(self.jobs)} server jobs · encrypted revision {self.revision}"
            )

    def _refresh_running_jobs(self):
        if (
            self.revision is not None
            and not self.pending
            and not self.dirty
            and any(item.get("running") for item in self.runtime.values())
        ):
            self._request("get_jobs")

    def _tick(self):
        if self.pending and time.monotonic() - self.pending[2] > 20:
            self.pending = None
            self._set_busy(False)
            self.status_label.setText(
                "No acknowledgment. Draft kept; Reload Server to confirm agent state."
            )

    def _connect_signals(self):
        if self._signals_connected:
            return
        self.bus.on("inbound.verified.rsync_boy.jobs", self._handle_jobs)
        self._signals_connected = True

    def _disconnect_signals(self):
        if not self._signals_connected:
            return
        self.bus.off("inbound.verified.rsync_boy.jobs", self._handle_jobs)
        self._signals_connected = False

    def _on_show(self):
        self.refresh_timer.start()
        if self.revision is None and not self.pending:
            self._request("get_jobs")

    def _on_hide(self):
        self.refresh_timer.stop()
        if self.pending:
            self.pending = None
            self._set_busy(False)
            self.status_label.setText(
                "Request interrupted. Reload Server to confirm the agent's state."
            )

    def get_panel_buttons(self):
        return [
            PanelButton(
                "💾",
                "Backup Jobs",
                lambda: self.session_window.show_specialty_panel(self),
            )
        ]
