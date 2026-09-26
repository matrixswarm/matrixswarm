from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QInputDialog, QLabel
)
from copy import deepcopy


class ServiceRolesMixin:
    """
    Mixin providing a standardized Service Manager Roles section
    for all agent config editors (Oracle, TrendScout, Sora, etc.)
    """

    def _build_roles_section(self, cfg, default_role=None):
        """
        Build the "Service Manager Roles" section.

        :param cfg: agent's config dict
        :param default_role: fallback role name if none exists
        """
        svc_mgr = cfg.get("service-manager", [])
        self._roles_invalid = not (
            isinstance(svc_mgr, list) and all(
                isinstance(entry, dict) and isinstance(entry.get("role", []), list)
                and all(isinstance(role, str) for role in entry.get("role", []))
                for entry in svc_mgr
            )
        )
        if svc_mgr and not self._roles_invalid:
            roles = svc_mgr[0].get("role", [])
        else:
            roles = []

        if "service-manager" not in cfg and default_role:
            roles = [default_role]

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.roles_list = QListWidget()
        for r in roles:
            self.roles_list.addItem(r)
        layout.addWidget(self.roles_list)

        # Buttons
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+")
        rm_btn = QPushButton("–")
        clr_btn = QPushButton("Clear")

        btn_row.addWidget(add_btn)
        btn_row.addWidget(rm_btn)
        btn_row.addWidget(clr_btn)
        layout.addLayout(btn_row)

        add_btn.clicked.connect(self._add_role)
        rm_btn.clicked.connect(self._remove_role)
        clr_btn.clicked.connect(self._clear_roles)

        # Attach container to the editor's form layout
        self.layout.addRow("Roles:", container)
        if self._roles_invalid:
            container.setEnabled(False)
            warning = QLabel("Invalid service metadata: role editing is disabled. "
                             "Existing metadata will be preserved unchanged on Save.")
            warning.setWordWrap(True)
            self.layout.addRow(warning)

    # --- Shared button helpers ---
    def _add_role(self):
        text, ok = QInputDialog.getText(
            self, "Add Role", "Enter role (example: trend_scout.topic_forge@cmd_topic_forge):"
        )
        if ok and text.strip():
            self.roles_list.addItem(text.strip())

    def _remove_role(self):
        for item in self.roles_list.selectedItems():
            self.roles_list.takeItem(self.roles_list.row(item))

    def _clear_roles(self):
        self.roles_list.clear()

    def _collect_roles(self, default_role=None):
        """Return a safe list of roles to save back to config."""
        roles = [self.roles_list.item(i).text() for i in range(self.roles_list.count())]
        if not roles and default_role:
            roles = [default_role]
        return roles

    def _service_manager_with_roles(self, roles):
        """Update only the edited roles, preserving routing/auth and other entries."""
        services = deepcopy(self.node.config.get("service-manager", []))
        if getattr(self, "_roles_invalid", False):
            return services
        if services == [] and not roles:
            return services
        if isinstance(services, list) and services and isinstance(services[0], dict):
            if "role" not in services[0] and not roles:
                return services
            services[0]["role"] = list(roles)
            return services
        return [{"role": list(roles)}]
