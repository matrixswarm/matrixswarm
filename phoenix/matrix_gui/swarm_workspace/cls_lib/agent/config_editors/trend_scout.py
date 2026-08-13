# Commander Edition – TrendScout Config Editor
# Mirrors Oracle editor UI exactly: typed fields, dropdowns, and proper service-manager role handling.

from .base_editor import BaseEditor
from PyQt6.QtWidgets import (QWidget, QLabel, QComboBox,
    QSpinBox, QFormLayout, QLineEdit
)
from .mixin.service_roles_mixin import ServiceRolesMixin
class TrendScout(BaseEditor, ServiceRolesMixin):
    def _build_form(self):
        cfg = self.config or {}

        # ---------------------------------------------------
        # TOPIC FORGE SETTINGS (semantic controls, cadence)
        # ---------------------------------------------------
        forge_box = QWidget()
        forge_layout = QFormLayout(forge_box)
        forge_layout.setContentsMargins(0, 0, 0, 0)
        forge_layout.setSpacing(4)

        # Mode dropdown (manual / auto)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["manual", "auto"])
        current_mode = (cfg.get("mode") or "manual").lower()
        if current_mode not in ("manual", "auto"):
            current_mode = "manual"
        self.mode_combo.setCurrentText(current_mode)

        # Boolean flags (dropdown style, same as Oracle's response_mode UI)
        self.enable_title = QComboBox()
        self.enable_title.addItems(["true", "false"])
        self.enable_title.setCurrentText("true" if str(cfg.get("enable_title_semantics", True)).lower() == "true" else "false")

        self.enable_tags = QComboBox()
        self.enable_tags.addItems(["true", "false"])
        self.enable_tags.setCurrentText("true" if str(cfg.get("enable_tag_semantics", True)).lower() == "true" else "false")

        # Video type (metrics-only)
        self.video_object_type = QSpinBox()
        self.video_object_type.setRange(1, 9999999)
        self.video_object_type.setValue(int(cfg.get("video_object_type", 5050)))

        # Cadence controls
        self.embed_interval = QSpinBox()
        self.embed_interval.setRange(60, 864000)
        self.embed_interval.setValue(int(cfg.get("embed_interval_sec", 21600)))

        self.cluster_interval = QSpinBox()
        self.cluster_interval.setRange(60, 864000)
        self.cluster_interval.setValue(int(cfg.get("cluster_interval_sec", 3600)))

        self.metrics_interval = QSpinBox()
        self.metrics_interval.setRange(60, 864000)
        self.metrics_interval.setValue(int(cfg.get("metrics_interval_sec", 3600)))

        # Idea generation cadence
        self.idea_interval = QSpinBox()
        self.idea_interval.setRange(60, 864000)
        self.idea_interval.setValue(int(cfg.get("idea_interval_sec", 86400)))

        self.auto_idea_count = QSpinBox()
        self.auto_idea_count.setRange(1, 50)
        self.auto_idea_count.setValue(int(cfg.get("auto_idea_count", 10)))

        self.idea_timer_enabled = QComboBox()
        self.idea_timer_enabled.addItems(["true", "false"])
        self.idea_timer_enabled.setCurrentText(
            "true" if str(cfg.get("idea_timer_enabled", False)).lower() == "true" else "false"
        )

        # Layout rows
        forge_layout.addRow("Mode:", self.mode_combo)
        forge_layout.addRow("Enable title semantics:", self.enable_title)
        forge_layout.addRow("Enable tag semantics:", self.enable_tags)
        forge_layout.addRow("Video object type:", self.video_object_type)
        forge_layout.addRow("Embedding interval (sec):", self.embed_interval)
        forge_layout.addRow("Cluster interval (sec):", self.cluster_interval)
        forge_layout.addRow("Metrics interval (sec):", self.metrics_interval)
        forge_layout.addRow("Idea interval (sec):", self.idea_interval)
        forge_layout.addRow("Auto idea count:", self.auto_idea_count)
        forge_layout.addRow("Idea timer enabled:", self.idea_timer_enabled)

        self.layout.addRow(QLabel("⚙️ Topic Forge Configuration"))
        self.layout.addRow(forge_box)

        # ---------------------------------------------------
        # ROUTING / ROLE SETTINGS
        # ---------------------------------------------------
        routing_box = QWidget()
        routing_layout = QFormLayout(routing_box)
        routing_layout.setContentsMargins(0, 0, 0, 0)
        routing_layout.setSpacing(4)

        self.oracle_role = QLineEdit(cfg.get("oracle_role", "hive.oracle"))
        self.rpc_router_role = QLineEdit(cfg.get("rpc_router_role", "hive.rpc"))
        self.gen_embeddings_role = QLineEdit(cfg.get("gen_embeddings_role", "hive.oracle.gen_embeddings"))
        self.cluster_labeler_role = QLineEdit(cfg.get("cluster_labeler_role", "hive.oracle.cluster_labeler"))
        self.sora_role = QLineEdit(cfg.get("sora_role", "hive.sora"))

        routing_layout.addRow("Oracle role:", self.oracle_role)
        routing_layout.addRow("Embedding role:", self.gen_embeddings_role)
        routing_layout.addRow("Cluster labeler role:", self.cluster_labeler_role)
        routing_layout.addRow("Sora role:", self.sora_role)

        self.layout.addRow(QLabel("🔀 Routing Roles"))
        self.layout.addRow(routing_box)

        # ---------------------------------------------------
        # SERVICE MANAGER SECTION (identical to Oracle editor)
        # ---------------------------------------------------
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="trend_scout.topic_forge@cmd_topic_forge")

        # store references for external use
        self.inputs = {
            "mode": self.mode_combo,
            "enable_title_semantics": self.enable_title,
            "enable_tag_semantics": self.enable_tags,
            "video_object_type": self.video_object_type,
            "embed_interval_sec": self.embed_interval,
            "cluster_interval_sec": self.cluster_interval,
            "metrics_interval_sec": self.metrics_interval,
            "idea_interval_sec": self.idea_interval,
            "auto_idea_count": self.auto_idea_count,
            "idea_timer_enabled": self.idea_timer_enabled,
            "rpc_router_role": self.rpc_router_role,
            "oracle_role": self.oracle_role,
            "gen_embeddings_role": self.gen_embeddings_role,
            "cluster_labeler_role": self.cluster_labeler_role,
            "sora_role": self.sora_role,
            "roles_list": self.roles_list,
        }


    # ---------------------------------------------------
    # SAVE — typed values, exact structure Oracle uses
    # ---------------------------------------------------
    def _save(self):

        roles = self._collect_roles()
        if not roles:
            roles = ["trend_scout.topic_forge@cmd_topic_forge"]

        self.node.config.update({
            "oracle_role": self.oracle_role.text().strip(),
            "rpc_router_role": self.rpc_router_role.text().strip(),
            "gen_embeddings_role": self.gen_embeddings_role.text().strip(),
            "cluster_labeler_role": self.cluster_labeler_role.text().strip(),
            "sora_role": self.sora_role.text().strip(),

            "video_object_type": int(self.video_object_type.value()),

            "embed_interval_sec": int(self.embed_interval.value()),
            "cluster_interval_sec": int(self.cluster_interval.value()),
            "metrics_interval_sec": int(self.metrics_interval.value()),

            "mode": self.mode_combo.currentText(),
            "idea_interval_sec": int(self.idea_interval.value()),
            "auto_idea_count": int(self.auto_idea_count.value()),
            "idea_timer_enabled": True if self.idea_timer_enabled.currentText() == "true" else False,

            "enable_title_semantics": True if self.enable_title.currentText() == "true" else False,
            "enable_tag_semantics": True if self.enable_tags.currentText() == "true" else False,

            "service-manager": [{"role": roles}],
        })

        self.node.mark_dirty()
        self.accept()
