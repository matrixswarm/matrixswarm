"""Structured, fail-closed Phoenix editor for the MCP Reflex airlock."""

from __future__ import annotations

from copy import deepcopy

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .base_editor import BaseEditor
from .mcp_reflex_model import (
    McpReflexConfigError,
    flatten_grants,
    validated_policy,
    validate_servers,
)


def _split_values(text: str) -> list[str]:
    return [item.strip() for item in text.replace(",", "\n").splitlines() if item.strip()]


class McpServerDialog(QDialog):
    """Edit one deployment-owned stdio MCP server definition."""

    def __init__(self, server_id="", config=None, parent=None):
        super().__init__(parent)
        cfg = config or {}
        self.setWindowTitle("MCP Server Definition")
        self.setMinimumWidth(680)
        layout = QFormLayout(self)

        self.server_id = QLineEdit(server_id)
        self.command = QLineEdit(str(cfg.get("command", "")))
        self.args = QPlainTextEdit("\n".join(cfg.get("args", [])))
        self.args.setPlaceholderText("One argument per line")
        self.args.setMaximumHeight(90)
        self.env = QPlainTextEdit(
            "\n".join(f"{key}={value}" for key, value in cfg.get("env", {}).items())
        )
        self.env.setPlaceholderText("Optional: one NAME=value entry per line")
        self.env.setMaximumHeight(90)
        self.allowed_tools = QLineEdit(", ".join(cfg.get("allowed_tools", [])))
        self.allowed_tools.setPlaceholderText("echo, status")
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 300)
        self.timeout.setValue(int(cfg.get("timeout_sec", 30)))

        layout.addRow("Server ID:", self.server_id)
        layout.addRow("Absolute command:", self.command)
        layout.addRow("Arguments:", self.args)
        layout.addRow("Environment:", self.env)
        layout.addRow("Server tool allowlist:", self.allowed_tools)
        layout.addRow("Timeout (sec):", self.timeout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def value(self):
        environment = {}
        for line in self.env.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            if "=" not in line or not line.split("=", 1)[0].strip():
                raise McpReflexConfigError(
                    "Environment entries must use NAME=value, one per line"
                )
            key, value = line.split("=", 1)
            environment[key.strip()] = value
        return self.server_id.text().strip(), {
            "command": self.command.text().strip(),
            "args": [line.strip() for line in self.args.toPlainText().splitlines() if line.strip()],
            "env": environment,
            "allowed_tools": _split_values(self.allowed_tools.text()),
            "timeout_sec": int(self.timeout.value()),
        }

    def _validate_and_accept(self):
        try:
            server_id, config = self.value()
            validate_servers({server_id: config})
        except McpReflexConfigError as exc:
            QMessageBox.warning(self, "Invalid MCP server", str(exc))
            return
        self.accept()


class McpGrantDialog(QDialog):
    """Edit one exact caller/server/tool grant."""

    def __init__(self, servers, grant=None, parent=None):
        super().__init__(parent)
        row = grant or {}
        self.servers = servers
        self.setWindowTitle("MCP Caller Grant")
        self.setMinimumWidth(620)
        layout = QFormLayout(self)

        self.caller_uid = QLineEdit(str(row.get("caller_uid", "")))
        self.caller_uid.setPlaceholderText("Exact generated agent UID")
        self.server_id = QComboBox()
        self.server_id.addItems(sorted(servers))
        if row.get("server_id") in servers:
            self.server_id.setCurrentText(row["server_id"])
        self.tools = QLineEdit(", ".join(row.get("tools", [])))
        self.tools.setPlaceholderText("Permitted tools for this caller")
        self.server_id.currentTextChanged.connect(self._refresh_hint)
        self.hint = QLabel()
        self.hint.setWordWrap(True)

        layout.addRow("Exact caller UID:", self.caller_uid)
        layout.addRow("Server:", self.server_id)
        layout.addRow("Permitted tools:", self.tools)
        layout.addRow("Server allows:", self.hint)
        self._refresh_hint(self.server_id.currentText())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _refresh_hint(self, server_id):
        tools = self.servers.get(server_id, {}).get("allowed_tools", [])
        self.hint.setText(", ".join(tools) if tools else "No tools configured")

    def value(self):
        return {
            "caller_uid": self.caller_uid.text().strip(),
            "server_id": self.server_id.currentText().strip(),
            "tools": _split_values(self.tools.text()),
        }


class McpReflex(BaseEditor):
    """Expose safe runtime limits and structured default-deny policy controls."""

    LIMITS = (
        ("max_workers", 1, 16, 2),
        ("max_pending", 1, 64, 8),
        ("worker_timeout_sec", 1, 360, 45),
        ("max_request_bytes", 1, 2_097_152, 262_144),
        ("max_result_bytes", 1, 2_097_152, 262_144),
        ("replay_window_sec", 1, 86_400, 300),
        ("max_completed_requests", 1, 65_536, 4_096),
    )

    def _build_form(self):
        cfg = self.config
        self.setMinimumWidth(760)
        self.setMinimumHeight(560)

        tabs = QTabWidget()
        limits_tab = QWidget()
        limits_layout = QFormLayout(limits_tab)
        servers_tab = QWidget()
        servers_layout = QVBoxLayout(servers_tab)
        grants_tab = QWidget()
        grants_layout = QVBoxLayout(grants_tab)
        tabs.addTab(limits_tab, "Security & Limits")
        tabs.addTab(servers_tab, "MCP Servers")
        tabs.addTab(grants_tab, "Caller Grants")
        self.layout.addRow(tabs)

        self.require_verified_identity = QCheckBox("Require verified Matrix identity")
        self.require_verified_identity.setChecked(
            cfg.get("require_verified_identity", True) is True
        )
        self.require_verified_identity.setEnabled(False)
        limits_layout.addRow(QLabel("🔐 Airlock Security"))
        limits_layout.addRow(self.require_verified_identity)
        limits_layout.addRow("Default policy:", QLabel("deny (enforced)"))

        self.limit_inputs = {}
        limits_layout.addRow(QLabel("⚙️ Worker Limits"))
        for name, minimum, maximum, default in self.LIMITS:
            widget = QSpinBox()
            widget.setRange(minimum, maximum)
            value = cfg.get(name, default)
            widget.setValue(value if isinstance(value, int) and not isinstance(value, bool) else default)
            self.limit_inputs[name] = widget
            limits_layout.addRow(name, widget)

        self._servers = deepcopy(cfg.get("servers", {}))
        self._grants = flatten_grants(cfg.get("access_control", {}))
        servers_layout.addWidget(QLabel(
            "Define each deployment-owned stdio MCP process and its complete tool allowlist."
        ))
        self.server_list = QListWidget()
        servers_layout.addWidget(self._button_section(
            self.server_list,
            self._add_server,
            self._edit_server,
            self._remove_server,
        ))

        grants_layout.addWidget(QLabel(
            "Grant an exact deployed caller UID access to selected tools on one server."
        ))
        self.grant_list = QListWidget()
        grants_layout.addWidget(self._button_section(
            self.grant_list,
            self._add_grant,
            self._edit_grant,
            self._remove_grant,
        ))
        note = QLabel(
            "Caller grants use the exact deployed agent UID. A tool must appear in "
            "both the server allowlist and the caller grant."
        )
        note.setWordWrap(True)
        grants_layout.addWidget(note)
        self._refresh_lists()

    def _button_section(self, list_widget, add_handler, edit_handler, remove_handler):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(list_widget)
        row = QHBoxLayout()
        for label, handler in (
            ("Add", add_handler), ("Edit", edit_handler), ("Remove", remove_handler)
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        list_widget.itemDoubleClicked.connect(lambda _item: edit_handler())
        return box

    def _refresh_lists(self):
        self.server_list.clear()
        for server_id in sorted(self._servers):
            config = self._servers[server_id]
            tools = ", ".join(config.get("allowed_tools", []))
            self.server_list.addItem(f"{server_id}  →  {config.get('command', '')}  [{tools}]")
        self.grant_list.clear()
        for row in self._grants:
            tools = ", ".join(row.get("tools", []))
            self.grant_list.addItem(
                f"{row.get('caller_uid', '')}  →  {row.get('server_id', '')}  [{tools}]"
            )

    def _selected_server_id(self):
        row = self.server_list.currentRow()
        return sorted(self._servers)[row] if 0 <= row < len(self._servers) else None

    def _add_server(self):
        dialog = McpServerDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        server_id, config = dialog.value()
        if server_id in self._servers:
            QMessageBox.warning(self, "Duplicate server", f"Server '{server_id}' already exists")
            return
        self._servers[server_id] = config
        self._refresh_lists()

    def _edit_server(self):
        old_id = self._selected_server_id()
        if old_id is None:
            return
        dialog = McpServerDialog(old_id, self._servers[old_id], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_id, config = dialog.value()
        if new_id != old_id and new_id in self._servers:
            QMessageBox.warning(self, "Duplicate server", f"Server '{new_id}' already exists")
            return
        del self._servers[old_id]
        self._servers[new_id] = config
        for grant in self._grants:
            if grant.get("server_id") == old_id:
                grant["server_id"] = new_id
        self._refresh_lists()

    def _remove_server(self):
        server_id = self._selected_server_id()
        if server_id is None:
            return
        del self._servers[server_id]
        self._grants = [row for row in self._grants if row.get("server_id") != server_id]
        self._refresh_lists()

    def _add_grant(self):
        if not self._servers:
            QMessageBox.information(self, "Add a server first", "Caller grants require an MCP server.")
            return
        dialog = McpGrantDialog(self._servers, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._grants.append(dialog.value())
            self._refresh_lists()

    def _edit_grant(self):
        row = self.grant_list.currentRow()
        if not 0 <= row < len(self._grants):
            return
        dialog = McpGrantDialog(self._servers, self._grants[row], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._grants[row] = dialog.value()
            self._refresh_lists()

    def _remove_grant(self):
        row = self.grant_list.currentRow()
        if 0 <= row < len(self._grants):
            del self._grants[row]
            self._refresh_lists()

    def _save(self):
        try:
            servers, access_control = validated_policy(self._servers, self._grants)
        except McpReflexConfigError as exc:
            QMessageBox.warning(self, "MCP policy not saved", str(exc))
            return
        self.node.config.update({
            "require_verified_identity": True,
            "servers": servers,
            "access_control": access_control,
            **{name: int(widget.value()) for name, widget in self.limit_inputs.items()},
        })
        self.node.mark_dirty()
        self.accept()
