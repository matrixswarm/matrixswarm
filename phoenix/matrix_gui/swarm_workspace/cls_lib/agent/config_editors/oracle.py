from .base_editor import BaseEditor
from PyQt6.QtWidgets import ( QWidget, QLabel, QComboBox, QDoubleSpinBox, QFormLayout
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
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
            "gpt-sora-1"
        ])
        self.model.setCurrentText(cfg.get("model", "gpt-3.5-turbo"))

        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(float(cfg.get("temperature", 0.7)))

        self.response_mode = QComboBox()
        self.response_mode.addItems(["terse", "verbose", "creative"])
        self.response_mode.setCurrentText(cfg.get("response_mode", "terse"))

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

        roles = self._collect_roles()

        # Update config dict
        self.node.config.update({
            "model": self.model.currentText(),
            "temperature": float(self.temperature.value()),
            "response_mode": self.response_mode.currentText(),
            "service-manager": [{"role": roles}]
        })

        self.node.mark_dirty()
        self.accept()
