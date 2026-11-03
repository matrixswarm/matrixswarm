"""Workspace configuration for LifeSignal's service roles."""
from PyQt6.QtWidgets import QLabel, QLineEdit, QMessageBox
from .base_editor import BaseEditor
from .mixin.service_roles_mixin import ServiceRolesMixin


class LifeSignal(BaseEditor, ServiceRolesMixin):
    PANEL_NAME = "LifeSignal"
    def _build_form(self):
        self.oracle_role = QLineEdit()
        self._load_saved_text(self.oracle_role, self.config.get('oracle_role', 'hive.oracle'))
        self.layout.addRow('Oracle service role:', self.oracle_role)
        note = QLabel(f'Add sources, keywords, and alert roles in the {self.PANEL_NAME} panel after deployment.')
        note.setWordWrap(True)
        self.layout.addRow(note)
        self.layout.addRow(QLabel('Service Manager Roles'))
        self._build_roles_section(self.config)

    def _save(self):
        try:
            role = self._saved_text(self.oracle_role, 'Oracle service role').strip()
            if not role or '@' in role or len(role) > 128:
                raise ValueError('Enter a service role without a handler.')
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid configuration', str(exc))
            return
        self.node.config.update({'oracle_role': role,
            'service-manager': self._service_manager_with_roles(self._collect_roles())})
        self.node.mark_dirty()
        self.accept()
