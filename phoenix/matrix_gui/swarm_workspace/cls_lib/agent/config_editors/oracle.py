from .base_editor import BaseEditor
from PyQt6.QtWidgets import ( QWidget, QLabel, QComboBox, QDoubleSpinBox, QFormLayout, QMessageBox
)
from .mixin.service_roles_mixin import ServiceRolesMixin
class Oracle(BaseEditor, ServiceRolesMixin):
    def _build_form(self):
        cfg = self.config

        # =======================================================
        # --- OPENAI SETTINGS SECTION ---
        # =======================================================
        openai_box = QWidget()
        openai_layout = QFormLayout(openai_box)
        openai_layout.setContentsMargins(0, 0, 0, 0)
        openai_layout.setSpacing(4)

        # API Key (not shown here by design — can be handled elsewhere)
        self.model = QComboBox()
        self.model.addItems([
            "gpt-5.6-terra",
            "gpt-5.6-sol",
            "gpt-6-astra",
            "gpt-4o",
        ])
        self._select_saved_choice(self.model, cfg.get("model", "gpt-5.6-terra"))

        self.temperature = QDoubleSpinBox()
        self.temperature.setDecimals(15)
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self._load_saved_number(self.temperature, cfg.get("temperature", 0))

        self.response_mode = QComboBox()
        self.response_mode.addItems(["terse", "verbose", "creative"])
        self._select_saved_choice(self.response_mode, cfg.get("response_mode", "terse"))

        openai_layout.addRow("Model:", self.model)
        openai_layout.addRow("Temperature:", self.temperature)
        openai_layout.addRow("Response Mode:", self.response_mode)

        self.layout.addRow(QLabel("⚙️ OpenAI Configuration"))
        self.layout.addRow(openai_box)

        # =======================================================
        # --- SERVICE MANAGER ROLES SECTION ---
        # =======================================================
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="hive.oracle@cmd_msg_prompt")

        # Keep input refs
        self.inputs = {
            "model": self.model,
            "temperature": self.temperature,
            "response_mode": self.response_mode,
            "roles_list": self.roles_list,
        }

    # =======================================================
    # SAVE LOGIC
    # =======================================================
    def _save(self):
        try:
            model = self._saved_choice(self.model, "Model")
            response_mode = self._saved_choice(self.response_mode, "Response mode")
            temperature = self._saved_number(self.temperature, "Temperature")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Configuration", str(exc))
            return
        roles = self._collect_roles()

        # Update config dict
        self.node.config.update({
            "model": model,
            "temperature": temperature,
            "response_mode": response_mode,
            "service-manager": self._service_manager_with_roles(roles)
        })

        self.node.mark_dirty()
        self.accept()
