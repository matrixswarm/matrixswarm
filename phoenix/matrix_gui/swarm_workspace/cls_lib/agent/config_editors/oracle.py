from .base_editor import BaseEditor
from PyQt6.QtWidgets import ( QWidget, QLabel, QComboBox, QDoubleSpinBox, QFormLayout, QMessageBox, QSpinBox
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

        self.max_input_chars = QSpinBox()
        self.max_input_chars.setRange(1000, 1000000)
        self.max_input_chars.setSingleStep(10000)
        self._load_saved_number(self.max_input_chars, cfg.get("max_input_chars", 200000))
        self.max_input_chars.setToolTip("Requests above this limit are rejected; messages are never silently removed. Model token limits also apply.")

        openai_layout.addRow("Model:", self.model)
        openai_layout.addRow("Temperature:", self.temperature)
        openai_layout.addRow("Response Mode:", self.response_mode)
        openai_layout.addRow("Maximum input characters:", self.max_input_chars)

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
            "max_input_chars": self.max_input_chars,
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
            max_input_chars = self._saved_number(self.max_input_chars, "Maximum input characters")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Configuration", str(exc))
            return
        roles = self._collect_roles()

        # Update config dict
        self.node.config.update({
            "model": model,
            "temperature": temperature,
            "response_mode": response_mode,
            "max_input_chars": max_input_chars,
            "service-manager": self._service_manager_with_roles(roles)
        })

        self.node.mark_dirty()
        self.accept()
