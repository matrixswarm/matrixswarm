"""Agent-scoped crypto watch editor; saved state lives on MatrixOS."""
import time
import uuid

from PyQt6.QtCore import QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QScrollArea,
)
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton

from .flow_layout import FlowLayout
from .alert_card import AlertCard


class CryptoAlert(PhoenixPanelInterface):
    cache_panel = True
    received = pyqtSignal(str, object)

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.agent_uid = (node or {}).get("universal_id")
        self.token = uuid.uuid4().hex
        self.alert_cards = []
        self.revision = None
        self.dirty = False
        self._edit_generation = 0
        self.pending = None
        self._signals_connected = False
        self._last_update = None
        self.setLayout(self._build_ui())
        self.received.connect(self._receive)
        self.renew_timer = QTimer(self)
        self.renew_timer.setInterval(20000)
        self.renew_timer.timeout.connect(self._start_price_stream)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self._tick)
        self._timers.extend([self.renew_timer, self.refresh_timer])
        self._set_busy(False)

    def _build_ui(self):
        layout = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel("Crypto Watches · Phemex spot + Bitcoin"))
        top.addStretch()
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Clean Cockpit", "Fusion Reactor", "Arcane Oracle"])
        self.style_combo.currentTextChanged.connect(self._update_styles)
        top.addWidget(self.style_combo)
        layout.addLayout(top)
        help_text = QLabel(
            "Pairs: BTC/USDT, BTC/ETH, etc. Cross-pairs are derived from USDT spot prices.\n"
            "Bitcoin watches use public addresses only; the configured explorer sees address queries.\n"
            "Save commits edits and deletions to encrypted agent state. Editing a watch resets its baseline and hit count."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.status_label = QLabel("Open this panel to load saved watches.")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.feed_label = QLabel("Feed: waiting")
        self.feed_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.feed_label)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.card_container = QWidget()
        self.card_layout = FlowLayout(self.card_container, spacing=12)
        self.scroll_area.setWidget(self.card_container)
        layout.addWidget(self.scroll_area, 1)
        row = QHBoxLayout()
        self.btn_add = QPushButton("＋ Price / Pair Watch")
        self.btn_wallet = QPushButton("＋ Bitcoin Address")
        self.btn_reload = QPushButton("Reload Saved")
        self.btn_save = QPushButton("Save Changes")
        self.btn_add.clicked.connect(lambda: self._add_card())
        self.btn_wallet.clicked.connect(lambda: self._add_card(wallet=True))
        self.btn_reload.clicked.connect(self._request_current_config)
        self.btn_save.clicked.connect(self._push_config)
        for button in (self.btn_add, self.btn_wallet, self.btn_reload, self.btn_save):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        return layout

    def _set_busy(self, busy):
        ready = self.revision is not None and not busy
        # An update may take a round trip through MatrixOS. Keep text fields
        # editable during that trip and reconcile any newer edits on the ack.
        loading = bool(busy and self.pending and self.pending[1] == "get_config")
        self.card_container.setEnabled(not loading)
        self.btn_add.setEnabled(ready)
        self.btn_wallet.setEnabled(ready)
        self.btn_save.setEnabled(ready)
        self.btn_reload.setEnabled(not busy)
        for card in self.alert_cards:
            card.delete_btn.setEnabled(not busy)

    def _mark_dirty(self):
        self._edit_generation += 1
        self.dirty = True
        self.status_label.setText("Unsaved changes — Save Changes applies the complete watch list.")
        for card in self.alert_cards:
            card._update_field_visibility()
            card.render_boiler()

    def _add_card(self, alert=None, wallet=False, draft=True):
        alert = alert or {
            "id": uuid.uuid4().hex, "pair": "BTC/USDT",
            "trigger_type": "wallet_change" if wallet else "price_above",
            "threshold": "", "from_amount": 0.1, "cooldown_sec": 60,
            "trigger_limit": 0, "active": True, "alert_enabled": True,
            "stream_enabled": True,
        }
        card = AlertCard(self.card_container)
        card.from_dict(alert)
        card.set_boiler_style(self.style_combo.currentText())
        card.changed.connect(lambda: self._card_edited(card))
        card._draft = draft
        card.delete_btn.clicked.connect(lambda: self._delete_card(card))
        self.card_layout.addWidget(card)
        self.alert_cards.append(card)
        card.render_boiler()
        if draft:
            self._mark_dirty()

    def _card_edited(self, card):
        card._draft = True
        self._mark_dirty()

    def _delete_card(self, card):
        if card not in self.alert_cards or self.pending:
            return
        self.alert_cards.remove(card)
        self.card_layout.removeWidget(card)
        card.setParent(None)
        card.deleteLater()
        self._mark_dirty()

    def _update_styles(self):
        for card in self.alert_cards:
            card.set_boiler_style(self.style_combo.currentText())
            card.render_boiler()

    def _send(self, service, **extra):
        request_id = extra.pop("request_id", uuid.uuid4().hex)
        payload = dict(extra, target_universal_id=self.agent_uid,
                       session_id=self.session_id, token=self.token, request_id=request_id)
        packet = Packet()
        packet.set_data({"handler": "cmd_service_request", "ts": time.time(),
                         "content": {"service": "hive.crypto_alert." + service, "payload": payload}})
        self.bus.emit("outbound.message", session_id=self.session_id,
                      channel="outgoing.command", packet=packet)
        return request_id

    def _request(self, operation, **extra):
        if self.pending:
            return
        request_id = uuid.uuid4().hex
        submitted = [dict(item) for item in extra.get("watch_list", [])]
        self.pending = (
            request_id,
            operation,
            time.monotonic(),
            self._edit_generation,
            submitted,
        )
        self._set_busy(True)
        self.status_label.setText("Saving encrypted state…" if operation == "update_config" else "Loading saved watches…")
        try:
            self._send(operation, request_id=request_id, **extra)
        except Exception:
            self.pending = None
            self._set_busy(False)
            self.status_label.setText("Request could not be sent. Your draft has been kept.")

    def _request_current_config(self):
        if self.dirty and QMessageBox.question(
            self, "Reload Saved Watches", "Discard unsaved edits and reload the agent's saved watches?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._request("get_config")

    def _push_config(self):
        if self.revision is None:
            return
        for index, card in enumerate(self.alert_cards, 1):
            invalid = card.validation_error()
            if invalid:
                message, widget = invalid
                self.status_label.setText(f"Watch {index} was not saved: {message}")
                self.scroll_area.ensureWidgetVisible(widget)
                widget.setFocus()
                widget.selectAll()
                return
        self._request("update_config", revision=self.revision,
                      watch_list=[card.to_dict() for card in self.alert_cards])

    def _handle_config_update(self, session_id, channel=None, source=None, payload=None, **_):
        self._accept_callback("config", session_id, payload)

    def _handle_price_update(self, session_id, channel=None, source=None, payload=None, **_):
        self._accept_callback("update", session_id, payload)

    def _accept_callback(self, kind, session_id, payload):
        if session_id != self.session_id or not isinstance(payload, dict):
            return
        content = payload.get("content")
        if (not isinstance(content, dict) or content.get("token") != self.token
                or content.get("agent_uid") != self.agent_uid):
            return
        # Bus callbacks may run outside the GUI thread.
        self.received.emit(kind, content)

    def _receive(self, kind, content):
        if not self._signals_connected:
            return
        if kind == "config":
            if not self.pending or content.get("request_id") != self.pending[0]:
                return
            pending = self.pending
            operation = pending[1]
            submitted_generation = pending[3] if len(pending) > 3 else self._edit_generation
            submitted_watches = pending[4] if len(pending) > 4 else []
            self.pending = None
            if not content.get("ok"):
                self._set_busy(False)
                self.status_label.setText("Not saved/loaded: " + str(content.get("error", "Agent rejected the request")))
                return
            if not isinstance(content.get("watch_list"), list) or type(content.get("revision")) is not int:
                self._set_busy(False)
                self.status_label.setText("Invalid agent response. Reload to confirm saved state.")
                return
            self.revision = content["revision"]
            edited_during_save = (
                operation == "update_config"
                and self._edit_generation != submitted_generation
            )
            if edited_during_save:
                submitted_by_id = {item.get("id"): item for item in submitted_watches}
                for card in self.alert_cards:
                    if card.to_dict() == submitted_by_id.get(card.alert_id):
                        card._draft = False
                    card.render_boiler()
                self.dirty = any(card._draft for card in self.alert_cards)
            else:
                while self.alert_cards:
                    card = self.alert_cards.pop()
                    self.card_layout.removeWidget(card)
                    card.setParent(None)
                    card.deleteLater()
                for alert in content["watch_list"]:
                    self._add_card(alert, draft=False)
                self.dirty = False
            self._set_busy(False)
            action = "Saved" if operation == "update_config" else "Loaded"
            if edited_during_save:
                self.status_label.setText(
                    f"Saved revision {self.revision}; newer edits remain unsaved. "
                    "Save Changes again when ready."
                )
            else:
                self.status_label.setText(f"{action} {len(self.alert_cards)} watches · encrypted state revision {self.revision}")
        elif content.get("revision") != self.revision:
            self.feed_label.setText("Saved watches changed — Reload Saved before editing further.")
            return
        self._last_update = time.monotonic()
        self.feed_label.setText("Phemex feed: " + str(content.get("feed_status", "unknown")))
        live, runtime = content.get("live", {}), content.get("runtime", {})
        for card in self.alert_cards:
            card.set_snapshot(live.get(card.alert_id, {}), runtime.get(card.alert_id, {}))

    def _start_price_stream(self):
        try:
            self._send("stream_prices")
        except Exception:
            self.feed_label.setText("Stream request could not be sent.")

    def _stop_price_stream(self):
        try:
            self._send("stop_stream")
        except Exception:
            pass  # Remote lease expires after 60 seconds if the transport is gone.

    def _tick(self):
        if self.pending and time.monotonic() - self.pending[2] > 20:
            self.pending = None
            self._set_busy(False)
            self.status_label.setText("No acknowledgment. Draft kept; Reload Saved to confirm what the agent stored.")
        if self._last_update is not None and time.monotonic() - self._last_update > 15:
            self.feed_label.setText("Panel stream stale — waiting for the agent; displayed values may be old.")
        for card in self.alert_cards:
            card.render_boiler()

    def _connect_signals(self):
        if self._signals_connected:
            return
        self.bus.on("inbound.verified.crypto_alert.config", self._handle_config_update)
        self.bus.on("inbound.verified.crypto_alert.update", self._handle_price_update)
        self._signals_connected = True

    def _disconnect_signals(self):
        if not self._signals_connected:
            return
        self.bus.off("inbound.verified.crypto_alert.config", self._handle_config_update)
        self.bus.off("inbound.verified.crypto_alert.update", self._handle_price_update)
        self._signals_connected = False

    def _on_show(self):
        self.refresh_timer.start()
        self.renew_timer.start()
        if self.revision is None and not self.pending:
            self._request("get_config")
        self._start_price_stream()

    def _on_hide(self):
        self.refresh_timer.stop()
        self.renew_timer.stop()
        self._stop_price_stream()
        if self.pending:
            self.pending = None
            self._set_busy(False)
            self.status_label.setText("Request interrupted. Reload Saved to confirm the agent's state.")

    def _on_close(self):
        self._stop_price_stream()

    def get_panel_buttons(self):
        return [PanelButton("📈", "Crypto Watches",
                            lambda: self.session_window.show_specialty_panel(self))]
