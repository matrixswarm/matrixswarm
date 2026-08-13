# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time
from typing import Dict, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QScrollArea
)

from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton

from .flow_layout import FlowLayout
from .alert_card import AlertCard


class CryptoAlert(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.node = node

        self.alert_cards: List[AlertCard] = []
        self.price_cache: Dict[str, Dict] = {}

        self._signals_connected = False

        # Build UI
        self.setLayout(self._build_ui())
        self._connect_signals()

        # Auto-start price feed
        self._start_price_stream()

    # -------------------------------------------------------------------
    # UI BUILD
    # -------------------------------------------------------------------
    def _build_ui(self):

        layout = QVBoxLayout()

        # Top row
        top = QHBoxLayout()
        top.addWidget(QLabel("📈 Commander Edition Crypto Alerts"))
        top.addStretch()

        top.addWidget(QLabel("Boiler Style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Clean Cockpit", "Fusion Reactor", "Arcane Oracle"])
        self.style_combo.currentTextChanged.connect(self._update_all_boiler_styles)
        top.addWidget(self.style_combo)

        layout.addLayout(top)

        # Scroll container for cards
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.card_container = QWidget()
        self.card_layout = FlowLayout(self.card_container, spacing=12)

        self.scroll_area.setWidget(self.card_container)
        layout.addWidget(self.scroll_area)

        # Toolbar
        row = QHBoxLayout()

        self.btn_add = QPushButton("➕ Add Watch")
        self.btn_add.clicked.connect(self._add_card)
        row.addWidget(self.btn_add)

        self.btn_reload = QPushButton("🔄 Reload Config")
        self.btn_reload.clicked.connect(self._request_current_config)
        row.addWidget(self.btn_reload)

        self.btn_push = QPushButton("🚀 Push Config")
        self.btn_push.clicked.connect(self._push_config)
        row.addWidget(self.btn_push)

        self.btn_save = QPushButton("💾 Save to Vault")
        self.btn_save.clicked.connect(self._save_to_vault)
        row.addWidget(self.btn_save)

        self.btn_load = QPushButton("📥 Load From Vault")
        self.btn_load.clicked.connect(self._load_from_vault)
        row.addWidget(self.btn_load)

        self.btn_stream_start = QPushButton("📡 Start Feed")
        self.btn_stream_start.clicked.connect(self._start_price_stream)
        row.addWidget(self.btn_stream_start)

        self.btn_stream_stop = QPushButton("🛑 Stop Feed")
        self.btn_stream_stop.clicked.connect(self._stop_price_stream)
        row.addWidget(self.btn_stream_stop)

        layout.addLayout(row)

        return layout

    # -------------------------------------------------------------------
    # Card helpers
    # -------------------------------------------------------------------
    def _add_card(self, alert=None):
        try:
            # Default new alert
            alert = alert or {
                "pair": "BTC/USDT",
                "trigger_type": "price_above",
                "threshold": 0.0,
                "active": True,
                "alert_enabled": True,
                "stream_enabled": True,
                "trigger_limit": 9999999
            }

            card = AlertCard(self.card_container)
            card.from_dict(alert)
            card.set_boiler_style(self.style_combo.currentText())
            card.delete_btn.clicked.connect(lambda: self._delete_card(card))

            self.card_layout.addWidget(card)
            self.alert_cards.append(card)
            card.render_boiler()

        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._add_card", e)

    def _delete_card(self, card: AlertCard):
        try:
            # 1. Remove it from GUI
            if card in self.alert_cards:
                idx = self.alert_cards.index(card)
            else:
                return

            # Fetch current watchlist
            wl = self._collect_watchlist()

            # 2. Remove the matching watch entry
            if 0 <= idx < len(wl):
                wl.pop(idx)

            # 3. Send RPC to backend to overwrite watch_list
            pk = Packet()
            pk.set_data({
                "handler": "cmd_update_agent",
                "content": {
                    "target_universal_id": self.node.get("universal_id"),
                    "config": {"watch_list": wl},
                    "push_live_config": True,
                },
                "ts": time.time(),
            })
            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk,
            )

            # 4. Remove the card visually
            self.alert_cards.remove(card)
            card.setParent(None)
            card.deleteLater()

        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._delete_card", e)

    # -------------------------------------------------------------------
    # Boiler updates
    # -------------------------------------------------------------------
    def _update_all_boiler_styles(self):
        style = self.style_combo.currentText()
        for card in self.alert_cards:
            card.set_boiler_style(style)
            card.render_boiler()

    def _refresh_all_boilers(self):
        for card in self.alert_cards:
            self._update_card_prices_from_cache(card)
            card.render_boiler()

    def _update_card_prices_from_cache(self, card):
        pair = card.pair_edit.text().strip()
        if pair in self.price_cache:
            info = self.price_cache[pair]
            card.set_live_price(info["price"], info["ts"])

        # Conversion extended data
        if card.trigger_combo.currentText() == "asset_conversion":
            fa = card.from_asset_edit.text().strip() or "BTC"
            ta = card.to_asset_edit.text().strip() or "ETH"

            p1 = self.price_cache.get(f"{fa}/USDT", {}).get("price")
            p2 = self.price_cache.get(f"{ta}/USDT", {}).get("price")

            if p1 is not None and p2 is not None:
                card.set_conversion_prices(p1, p2)

    # -------------------------------------------------------------------
    # Data extraction
    # -------------------------------------------------------------------
    def _collect_watchlist(self) -> List[Dict]:
        return [card.to_dict() for card in self.alert_cards]

    # -------------------------------------------------------------------
    # Push config to backend
    # -------------------------------------------------------------------
    def _push_config(self):
        try:
            wl = self._collect_watchlist()
            if not wl:
                QMessageBox.warning(self, "Nothing to Push", "No alerts defined.")
                return

            pk = Packet()
            pk.set_data({
                "handler": "cmd_update_agent",
                "content": {
                    "target_universal_id": self.node.get("universal_id"),
                    "config": {"watch_list": wl},
                    "push_live_config": True,
                },
                "ts": time.time()
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk
            )

            QMessageBox.information(self, "Updated", "Config pushed to backend.")

        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._push_config", e)

    # -------------------------------------------------------------------
    # Load config FROM backend
    # -------------------------------------------------------------------
    def _request_current_config(self):
        try:
            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "hive.crypto_alert.get_config",
                    "payload": {"session_id": self.session_id}
                }
            })
            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk
            )
        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._request_current_config", e)

    def _populate_from_agent(self, cfg: Dict):
        try:
            for c in self.alert_cards:
                c.setParent(None)
                c.deleteLater()

            self.alert_cards.clear()

            for alert in cfg.get("watch_list", []):
                self._add_card(alert)

            self._refresh_all_boilers()

        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._populate_from_agent", e)

    # -------------------------------------------------------------------
    # Vault save / load
    # -------------------------------------------------------------------
    def _save_to_vault(self):
        try:
            wl = self._collect_watchlist()
            vault = VaultConnectionSingleton.get()
            vault.update_field("crypto_alerts", wl)
            QMessageBox.information(self, "Vault", "Saved to vault.")
        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._save_to_vault", e)

    def _load_from_vault(self):
        try:
            vault = VaultConnectionSingleton.get()
            wl = vault.get_field("crypto_alerts", [])
            self._populate_from_agent({"watch_list": wl})
            QMessageBox.information(self, "Vault", "Loaded from vault.")
        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._load_from_vault", e)

    # -------------------------------------------------------------------
    # Streaming commands
    # -------------------------------------------------------------------
    def _start_price_stream(self):
        try:
            token = f"crypto_gui_{int(time.time())}"

            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "hive.crypto_alert.stream_prices",
                    "payload": {
                        "session_id": self.session_id,
                        "token": token,
                        "return_handler": "crypto_alert.update",
                    },
                },
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk
            )

        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._start_price_stream", e)

    def _stop_price_stream(self):
        try:
            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "hive.crypto_alert.stop_stream",
                    "payload": {"session_id": self.session_id}
                }
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk
            )

        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._stop_price_stream", e)

    # -------------------------------------------------------------------
    # Packet handlers
    # -------------------------------------------------------------------
    def _handle_config_update(self, session_id, channel, source, payload, **_):
        try:
            content = payload.get("content", {}) or {}
            cfg = content.get("config", {}) or content

            if not isinstance(cfg, dict):
                return

            self._populate_from_agent(cfg)

        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._handle_config_update", e)

    def _handle_price_update(self, session_id, channel, source, payload, **_):
        """Handle inbound crypto_alert.update streaming packets."""
        try:
            content = payload.get("content", {})
            updates = content.get("updates", [])

            if not isinstance(updates, list):
                return

            now = time.time()
            for u in updates:
                if not isinstance(u, dict):
                    continue
                pair = u.get("pair")
                price = u.get("price")
                ts = u.get("ts", now)
                if pair and price is not None:
                    self.price_cache[pair] = {
                        "price": float(price),
                        "ts": float(ts)
                    }

            self._refresh_all_boilers()

        except Exception as e:
            emit_gui_exception_log("CryptoAlertPanel._handle_price_update", e)

    # -------------------------------------------------------------------
    # Panel/buttons
    # -------------------------------------------------------------------
    def get_panel_buttons(self):
        return [
            PanelButton("📈", "Crypto Alerts",
                        lambda: self.session_window.show_specialty_panel(self))
        ]

    # -------------------------------------------------------------------
    # Signals
    # -------------------------------------------------------------------
    def _connect_signals(self):
        try:
            if self._signals_connected:
                return
            self._signals_connected = True

            self.bus.on("inbound.verified.crypto_alert.update",
                        self._handle_price_update)
            self.bus.on("inbound.verified.crypto_alert.config",
                        self._handle_config_update)

        except Exception as e:
            emit_gui_exception_log("CryptoAlert._connect_signals", e)

    def _disconnect_signals(self):
        pass

    def _on_close(self):
        if self._signals_connected:
            try:
                self.bus.off("inbound.verified.crypto_alert.update",
                             self._handle_price_update)
                self.bus.off("inbound.verified.crypto_alert.config",
                             self._handle_config_update)
                self._signals_connected = False

            except Exception as e:
                emit_gui_exception_log("CryptoAlert._disconnect_signals", e)
