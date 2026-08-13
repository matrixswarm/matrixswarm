# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
# TREND SCOUT TOPIC FORGE PANEL — DB-backed Ideas → Curate → Fire (via Matrix service routing)

import time
import json
import uuid

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QMessageBox, QWidget, QLineEdit,
    QComboBox, QListWidget, QListWidgetItem, QSplitter
)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox

from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from PyQt6.QtWidgets import QSizePolicy


class TrendScout(PhoenixPanelInterface):
    """
    Commander Edition — TrendScout Topic Forge Panel

    Goals:
      • ALWAYS proxy through Matrix using cmd_service_request (service-manager resolution).
      • ALWAYS DB-backed (no JSON files).
      • Get 10 idea topics → user curates → Fire sends curated list to Sora.
      • Modify: select topic → give instruction → generate new 10 (replaces list).
      • Mode switch: manual/auto for TrendScout’s scheduled behavior.
      • Timer controls: show next scheduled execution + reset timer.

    Backend contract (single service string):
      service: "trend_scout.topic_forge"
      payload.action:
        - "generate_ideas"      {count}
        - "modify_ideas"        {base_topic, instruction, count}
        - "curate_add"          {idea_id}
        - "curate_add_all"      {batch_id}
        - "curate_remove"       {curated_id}
        - "curate_list"         {}
        - "fire"                {}
        - "mode_set"            {mode: "manual"|"auto"}
        - "mode_get"            {}
        - "timer_get"           {}
        - "timer_reset"         {}
    """

    cache_panel = True

    # === Matrix-resolved service name (must exist in TrendScout service-manager) ===
    SERVICE = "trend_scout.topic_forge"

    # === TrendScout will crypto_reply to this handler name ===
    ACK_HANDLER = "trend_scout_panel.topic_forge_ack"

    # === Bus topic for inbound verified callbacks ===
    BUS_ACK_TOPIC = "inbound.verified.trend_scout_panel.topic_forge_ack"

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)

        self._signals_connected = False

        # panel state
        self.last_curated = []   # list[dict]
        self._pending_tokens = set()

        layout = self._build_layout()
        self.setLayout(layout)

        self._connect_signals()

        print("[TREND_FORGE] Topic Forge panel online.")

    # ---------------------------------------------------------
    # UI LAYOUT
    # ---------------------------------------------------------
    def _build_layout(self):
        root = QVBoxLayout()
        root.setContentsMargins(4, 2, 4, 2)
        root.setSpacing(4)

        # ======================================================
        # Compact Sora Settings Strip (fixed-height)
        # ======================================================
        sora_strip = QWidget()
        sora_strip_lay = QHBoxLayout(sora_strip)
        sora_strip_lay.setContentsMargins(4, 0, 4, 0)
        sora_strip_lay.setSpacing(8)

        # --- Model
        sora_strip_lay.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["sora-2", "sora-2-pro"])
        self.model_combo.setMaximumWidth(120)
        self.model_combo.setFixedHeight(24)
        sora_strip_lay.addWidget(self.model_combo)

        # --- Resolution
        sora_strip_lay.addWidget(QLabel("Resolution:"))
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["720x1280", "1280x720"])
        self.resolution_combo.setMaximumWidth(120)
        self.resolution_combo.setFixedHeight(24)
        sora_strip_lay.addWidget(self.resolution_combo)

        # --- Duration
        sora_strip_lay.addWidget(QLabel("Duration:"))
        self.duration_combo = QComboBox()
        self.duration_combo.addItems(["4", "8", "12"])
        self.duration_combo.setCurrentText("12")
        self.duration_combo.setMaximumWidth(80)
        self.duration_combo.setFixedHeight(24)
        sora_strip_lay.addWidget(self.duration_combo)

        # --- Use Previous Frame Checkbox
        self.chk_use_prev = QCheckBox("Use prev frame")
        self.chk_use_prev.setToolTip("If checked, each step after the first will upload the prior frame as Sora's reference image.")
        self.chk_use_prev.setChecked(False)  # default ON if you want
        sora_strip_lay.addWidget(self.chk_use_prev)

        # --- Still Image URL (optional)
        self.input_ref_label = QLabel("Ref Img URL:")
        self.input_ref_label.setToolTip("Optional: A still image to use as Sora's reference for STEP 1.")
        sora_strip_lay.addWidget(self.input_ref_label)

        self.input_ref_edit = QLineEdit()
        self.input_ref_edit.setPlaceholderText("https://example.com/my_image.png")
        self.input_ref_edit.setFixedWidth(260)
        sora_strip_lay.addWidget(self.input_ref_edit)

        # --- Fire Button
        self.btn_fire = QPushButton("🔥 Fire!")
        self.btn_fire.setStyleSheet("font-weight:bold; padding:2px 8px;")
        self.btn_fire.setFixedHeight(24)
        self.btn_fire.clicked.connect(self._on_fire)
        sora_strip_lay.addWidget(self.btn_fire)

        # push everything left; no extra expanding widgets on the right
        sora_strip_lay.addStretch()

        # KEY: top strip must NOT expand vertically
        sora_strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sora_strip.setMaximumHeight(32)

        # no stretch on this row
        root.addWidget(sora_strip, 0)

        # ======================================================
        # Horizontal Split — Editor | Curated List
        # ======================================================
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # --- Left: Prompt Editor
        add_box = QGroupBox("Add / Edit Prompt")
        add_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        add_lay = QVBoxLayout(add_box)
        add_lay.setContentsMargins(4, 2, 4, 2)
        add_lay.setSpacing(4)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("Type or edit your prompt here…")
        self.prompt_edit.setMinimumHeight(240)
        self.prompt_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        add_lay.addWidget(self.prompt_edit)

        self.btn_add_prompt = QPushButton("➕ Add / Update")
        self.btn_add_prompt.setStyleSheet("padding: 4px;")
        self.btn_add_prompt.clicked.connect(self._on_add_prompt)
        add_lay.addWidget(self.btn_add_prompt)
        split.addWidget(add_box)

        # --- Right: Curated List
        curated_box = QGroupBox("Curated Sora List")
        curated_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        curated_lay = QVBoxLayout(curated_box)
        curated_lay.setContentsMargins(4, 2, 4, 2)
        curated_lay.setSpacing(4)

        self.curated_list = QListWidget()
        self.curated_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.curated_list.itemDoubleClicked.connect(self._on_edit_curated)
        curated_lay.addWidget(self.curated_list)

        self.btn_remove_curated = QPushButton("❌ Remove Selected")
        self.btn_remove_curated.setStyleSheet("padding: 4px;")
        self.btn_remove_curated.clicked.connect(self._on_remove_curated)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addWidget(self.btn_remove_curated)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_fire)  # same Fire button, just also visible down here
        curated_lay.addLayout(btn_row)

        split.addWidget(curated_box)

        # let the splitter own all the extra vertical space
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)  # stretch=1 → this row expands, top strip does not

        # ======================================================
        # Hidden Debug Output
        # ======================================================
        self.preview_box = QTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setVisible(False)
        self.preview_box.setMaximumHeight(100)
        self.preview_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.preview_box, 0)

        return root

    def _on_add_prompt(self):
        text = self.prompt_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Empty Prompt", "Type something first.")
            return

        idea = {
            "topic": text,
            "tags": [],
            "description": ""
        }

        item = QListWidgetItem(text[:120])
        item.setData(Qt.ItemDataRole.UserRole, idea)

        # ALWAYS append — never edit
        self.curated_list.addItem(item)

        # Clear editor + selection
        self.prompt_edit.clear()
        self.curated_list.clearSelection()

    def _on_edit_curated(self, item):
        """Double-click an item to edit it in the left text box."""
        idea = item.data(Qt.ItemDataRole.UserRole)
        self.prompt_edit.setPlainText(idea.get("topic", ""))
        self.curated_list.setCurrentItem(item)

    # ---------------------------------------------------------
    # Packet sender (ALWAYS via Matrix cmd_service_request)
    # ---------------------------------------------------------
    def _send_service(self, action: str, extra: dict | None = None):
        """
        Always route via Matrix cmd_service_request so Matrix resolves
        'service' using TrendScout service-manager roles (like your macro pattern). :contentReference[oaicite:2]{index=2}
        """
        extra = extra or {}

        token = f"trendforge_{uuid.uuid4().hex[:10]}"
        self._pending_tokens.add(token)

        payload = {
            "action": action,
            "session_id": self.session_id,
            "return_handler": self.ACK_HANDLER,
            "token": token,
        }
        payload.update(extra)

        pk = Packet()
        pk.set_data({
            "handler": "cmd_service_request",
            "ts": time.time(),
            "content": {
                "service": self.SERVICE,
                "payload": payload
            }
        })

        # mirror to debug tab
        try:
            self.preview_box.setPlainText(json.dumps(pk.get_packet(), indent=2))
        except Exception:
            pass

        self.bus.emit(
            "outbound.message",
            session_id=self.session_id,
            channel="outgoing.command",
            packet=pk,
        )

    # ---------------------------------------------------------
    # UI actions
    # ---------------------------------------------------------

    def _on_remove_curated(self):
        row = self.curated_list.currentRow()
        if row >= 0:
            item = self.curated_list.takeItem(row)
            topic = (item.data(Qt.ItemDataRole.UserRole) or {}).get("topic", "?")
            self.preview_box.append(f"❌ Removed '{topic}' from local curated list.")

    def _on_fire(self):
        # Collect curated ideas from the UI list
        curated_items = []
        for i in range(self.curated_list.count()):
            item = self.curated_list.item(i)
            idea = item.data(Qt.ItemDataRole.UserRole)
            if idea:
                curated_items.append({
                    "topic": idea.get("topic", ""),
                    "tags": idea.get("tags", []),
                    "description": idea.get("description", "")
                })

        if not curated_items:
            resp = QMessageBox.question(
                self,
                "Curated List Empty",
                "No items in the curated list. Fire anyway?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Ok:
                return

        model = self.model_combo.currentText()
        resolution = self.resolution_combo.currentText()
        try:
            duration_sec = int(self.duration_combo.currentText())
        except ValueError:
            duration_sec = 8  # fallback

        self._send_service("fire", {
            "curated_batch": curated_items,
            "model": model,
            "resolution": resolution,
            "duration_sec": duration_sec,
            "use_prev_frame": int(self.chk_use_prev.isChecked()),
            "input_reference_url": self.input_ref_edit.text().strip()
        })

        # Clear curated list and editor after firing
        self.curated_list.clear()
        self.prompt_edit.clear()

    # ---------------------------------------------------------
    # ACK handler from TrendScout (via Matrix verified inbound)
    # ---------------------------------------------------------
    def _handle_topic_forge_ack(self, session_id, channel, source, payload, **_):
        try:
            if session_id != self.session_id:
                return

            content = payload.get("content", payload) or {}
            token = content.get("token")
            if token and token in self._pending_tokens:
                self._pending_tokens.discard(token)

            status = content.get("status", "ok")
            action = content.get("action", "unknown")

            # fire doesn't need special UI, just log the message
            # no mode/timer/curate_list handling in lite mode

            # keep debug pane helpful
            try:
                self.preview_box.setPlainText(json.dumps(content, indent=2))
            except Exception:
                pass

        except Exception as e:
            emit_gui_exception_log("TrendScout._handle_topic_forge_ack", e)


    # ---------------------------------------------------------
    # Panel handling
    # ---------------------------------------------------------
    def get_panel_buttons(self):
        return [
            PanelButton("🎯", "Trend Topics", lambda: self.session_window.show_specialty_panel(self))
        ]

    def on_deployment_updated(self, deployment):
        # no-op
        pass

    # ---------------------------------------------------------
    # Bus Handlers (persistent)
    # ---------------------------------------------------------

    def _connect_signals(self):
        try:
            if not self._signals_connected:

                self.bus.on("inbound.verified.trend_scout_panel.topic_forge_ack", self._handle_topic_forge_ack)
                self._signals_connected = True

        except Exception as e:
            emit_gui_exception_log("CryptoAlert._connect_signals", e)

    def _disconnect_signals(self):
        pass

    def _on_close(self):

        try:
            if self._signals_connected:

                self.bus.off("inbound.verified.trend_scout_panel.topic_forge_ack", self._handle_topic_forge_ack)
                self._signals_connected = False

        except Exception as e:
            emit_gui_exception_log("CryptoAlert._disconnect_signals", e)
