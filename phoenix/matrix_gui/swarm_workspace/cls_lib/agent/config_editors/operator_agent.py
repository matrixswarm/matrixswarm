"""Phoenix editor for fixed, two-party operator-agent workflows."""

from __future__ import annotations

import json
from copy import deepcopy

from PyQt6.QtWidgets import (
    QCheckBox,
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
from .operator_agent_model import (
    OperatorAgentConfigError,
    validated_operator_policy,
)


def _split_values(text: str) -> list[str]:
    return [item.strip() for item in text.replace(",", "\n").splitlines() if item.strip()]


class OperatorWorkflowDialog(QDialog):
    """Edit a fixed MCP request; operators never provide runtime arguments."""

    def __init__(self, workflow_id="", workflow=None, parent=None):
        super().__init__(parent)
        row = workflow or {}
        self.setWindowTitle("Operator Workflow")
        self.setMinimumWidth(680)
        layout = QFormLayout(self)

        self.workflow_id = QLineEdit(workflow_id)
        self.server_id = QLineEdit(str(row.get("server_id", "")))
        self.tool_name = QLineEdit(str(row.get("tool_name", "")))
        self.arguments = QPlainTextEdit(
            json.dumps(row.get("arguments", {}), indent=2, sort_keys=True)
        )
        self.arguments.setMinimumHeight(150)
        self.turn_budget = QSpinBox()
        self.turn_budget.setRange(1, 128)
        self.turn_budget.setValue(int(row.get("turn_budget", 1)))
        fixed = QLabel(
            "Approval required — the requester cannot supply or override these arguments."
        )
        fixed.setWordWrap(True)

        layout.addRow("Workflow ID:", self.workflow_id)
        layout.addRow("MCP server ID:", self.server_id)
        layout.addRow("MCP tool name:", self.tool_name)
        layout.addRow("Fixed JSON arguments:", self.arguments)
        layout.addRow("Turn budget:", self.turn_budget)
        layout.addRow("Security:", fixed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def value(self):
        try:
            arguments = json.loads(self.arguments.toPlainText().strip() or "{}")
        except json.JSONDecodeError as exc:
            raise OperatorAgentConfigError("fixed arguments must be valid JSON") from exc
        return self.workflow_id.text().strip(), {
            "server_id": self.server_id.text().strip(),
            "tool_name": self.tool_name.text().strip(),
            "arguments": arguments,
            "requires_approval": True,
            "turn_budget": int(self.turn_budget.value()),
        }

    def _validate_and_accept(self):
        try:
            workflow_id, workflow = self.value()
            validated_operator_policy(
                enabled=True,
                requesters=["requester-1"],
                approvers=["approver-1"],
                workflows={workflow_id: workflow},
                limits={},
            )
        except OperatorAgentConfigError as exc:
            QMessageBox.warning(self, "Invalid operator workflow", str(exc))
            return
        self.accept()


class OperatorAgent(BaseEditor):
    """Configure exact identities and fixed approval-required MCP workflows."""

    LIMITS = (
        ("max_active_runs", 1, 64, 8),
        ("max_retained_runs", 1, 1_024, 128),
        ("default_turn_budget", 1, 128, 4),
        ("max_pending_mcp_requests", 1, 128, 8),
        ("mcp_request_timeout_sec", 1, 600, 60),
    )

    def _build_form(self):
        cfg = self.config
        self.setMinimumWidth(760)
        self.setMinimumHeight(560)
        tabs = QTabWidget()
        policy_tab = QWidget()
        policy_layout = QFormLayout(policy_tab)
        workflows_tab = QWidget()
        workflows_layout = QVBoxLayout(workflows_tab)
        tabs.addTab(policy_tab, "Approval Policy")
        tabs.addTab(workflows_tab, "Fixed Workflows")
        self.layout.addRow(tabs)

        self.enabled = QCheckBox("Enable operator-agent execution")
        self.enabled.setChecked(cfg.get("enabled") is True)
        self.requesters = QPlainTextEdit("\n".join(cfg.get("authorized_requester_uids", [])))
        self.requesters.setPlaceholderText("Exact deployed requester UID; one per line")
        self.requesters.setMaximumHeight(90)
        self.approvers = QPlainTextEdit("\n".join(cfg.get("authorized_approver_uids", [])))
        self.approvers.setPlaceholderText("Exact deployed approver UID; one per line")
        self.approvers.setMaximumHeight(90)
        distinct = QLabel("Required and enforced: the requester cannot approve its own run.")
        distinct.setWordWrap(True)
        policy_layout.addRow(self.enabled)
        policy_layout.addRow("Requester UIDs:", self.requesters)
        policy_layout.addRow("Approver UIDs:", self.approvers)
        policy_layout.addRow("Two-person control:", distinct)

        self.limit_inputs = {}
        for name, minimum, maximum, default in self.LIMITS:
            widget = QSpinBox()
            widget.setRange(minimum, maximum)
            value = cfg.get(name, default)
            widget.setValue(value if isinstance(value, int) and not isinstance(value, bool) else default)
            self.limit_inputs[name] = widget
            policy_layout.addRow(name, widget)

        self._workflows = deepcopy(cfg.get("workflows", {}))
        note = QLabel(
            "Each workflow has one fixed server, tool, and JSON argument mapping. "
            "After deployment, add this exact operator-agent UID and the same tool "
            "to MCP Reflex Caller Grants."
        )
        note.setWordWrap(True)
        workflows_layout.addWidget(note)
        self.workflow_list = QListWidget()
        workflows_layout.addWidget(self.workflow_list)
        buttons = QHBoxLayout()
        for label, handler in (("Add", self._add_workflow), ("Edit", self._edit_workflow), ("Remove", self._remove_workflow)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        workflows_layout.addLayout(buttons)
        self.workflow_list.itemDoubleClicked.connect(lambda _item: self._edit_workflow())
        self._refresh_workflows()

    def _refresh_workflows(self):
        self.workflow_list.clear()
        for workflow_id in sorted(self._workflows):
            workflow = self._workflows[workflow_id]
            self.workflow_list.addItem(
                f"{workflow_id}  →  {workflow.get('server_id', '')} / {workflow.get('tool_name', '')}"
            )

    def _selected_workflow_id(self):
        row = self.workflow_list.currentRow()
        keys = sorted(self._workflows)
        return keys[row] if 0 <= row < len(keys) else None

    def _add_workflow(self):
        dialog = OperatorWorkflowDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        workflow_id, workflow = dialog.value()
        if workflow_id in self._workflows:
            QMessageBox.warning(self, "Duplicate workflow", f"Workflow '{workflow_id}' already exists")
            return
        self._workflows[workflow_id] = workflow
        self._refresh_workflows()

    def _edit_workflow(self):
        old_id = self._selected_workflow_id()
        if old_id is None:
            return
        dialog = OperatorWorkflowDialog(old_id, self._workflows[old_id], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_id, workflow = dialog.value()
        if new_id != old_id and new_id in self._workflows:
            QMessageBox.warning(self, "Duplicate workflow", f"Workflow '{new_id}' already exists")
            return
        del self._workflows[old_id]
        self._workflows[new_id] = workflow
        self._refresh_workflows()

    def _remove_workflow(self):
        workflow_id = self._selected_workflow_id()
        if workflow_id is not None:
            del self._workflows[workflow_id]
            self._refresh_workflows()

    def _save(self):
        try:
            policy = validated_operator_policy(
                enabled=self.enabled.isChecked(),
                requesters=_split_values(self.requesters.toPlainText()),
                approvers=_split_values(self.approvers.toPlainText()),
                workflows=self._workflows,
                limits={name: int(widget.value()) for name, widget in self.limit_inputs.items()},
            )
        except OperatorAgentConfigError as exc:
            QMessageBox.warning(self, "Operator policy not saved", str(exc))
            return
        self.node.config.update(policy)
        self.node.mark_dirty()
        self.accept()
