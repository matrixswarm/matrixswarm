from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSizePolicy, QComboBox, QSpinBox, QMessageBox, QScrollArea, QGroupBox, QCheckBox, QLayout)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import QRect, QSize, Qt, QPoint, QTimer
import os
import json
import requests
import time
import uuid
import traceback
from core.class_lib.packet_delivery.mixin.packet_delivery_factory_mixin import PacketDeliveryFactoryMixin
from core.class_lib.packet_delivery.mixin.packet_reception_factory_mixin import PacketReceptionFactoryMixin
from core.class_lib.packet_delivery.mixin.packet_factory_mixin import PacketFactoryMixin


class CryptoAlertPanel(QWidget, PacketFactoryMixin, PacketDeliveryFactoryMixin, PacketReceptionFactoryMixin):

    def __init__(self, alert_path, back_callback=None):
        super().__init__()
        self.alert_path = alert_path
        self.alerts = []
        self.price_cache = {}
        self.price_last_fetch = 0
        self.back_callback = back_callback

        self.layout = QVBoxLayout(self)

        # Presets
        self.default_alert_presets = {
            "price_above": {"pair": "BTC/USDT", "threshold": 50000, "cooldown": 300},
            "price_below": {"pair": "BTC/USDT", "threshold": 20000, "cooldown": 300},
            "asset_conversion": {"from_asset": "BTC", "to_asset": "ETH", "from_amount": 0.1, "threshold": 1.0,
                                 "cooldown": 300},
            "price_change_above": {"pair": "BTC/USDT", "change_percent": 1.5, "cooldown": 300}
        }

        self.trigger_type_options = [
            ("Price Change - Above", "price_change_above"),
            ("Price Change - Below", "price_change_below"),
            ("Price Delta - Above", "price_delta_above"),
            ("Price Delta - Below", "price_delta_below"),
            ("Price Above", "price_above"),
            ("Price Below", "price_below"),
            ("Asset Conversion", "asset_conversion")
        ]

        self.supported_pairs = [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "XRP/USDT", "LTC/USDT",
            "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "ARB/USDT", "OP/USDT", "MATIC/USDT",
            "UNI/USDT", "AAVE/USDT", "SNX/USDT", "CRV/USDT", "SHIB/USDT", "PEPE/USDT"
        ]

        self.supported_assets = [
            "BTC", "ETH", "SOL", "ADA", "XRP", "LTC", "DOGE", "AVAX", "DOT", "ARB", "OP", "MATIC",
            "UNI", "AAVE", "SNX", "CRV", "SHIB", "PEPE", "USDT"
        ]

        #CryptoAlertPanel.setStyleSheet("""
        #    * {
        #        font-family: Consolas, Courier, monospace;
        #    }
        #""")

        # Top row: Add new alert
        self.top_row = QHBoxLayout()
        self.trigger_selector = QComboBox()
        for label, value in self.trigger_type_options:
            self.trigger_selector.addItem(label, value)
        self.add_button = QPushButton("➕ Add")
        self.add_button.clicked.connect(self.prefill_new_alert)
        self.top_row.addWidget(QLabel("Alert Types:"))
        self.top_row.addWidget(self.trigger_selector)
        self.top_row.addWidget(self.add_button)
        self.layout.addLayout(self.top_row)

        # Scrollable Alert Cards Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.card_container = QWidget()
        self.card_layout = FlowLayout(self.card_container, spacing=12)

        self.card_container.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.card_container.setMinimumWidth(600)
        self.scroll_area.setWidget(self.card_container)
        self.layout.addWidget(QLabel("📈 Active Crypto Alerts"))
        self.layout.addWidget(self.scroll_area)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)


        # Back Button
        self.back_btn = QPushButton("⬅️ Back to Hive")
        self.back_btn.clicked.connect(self.handle_back)
        self.layout.addWidget(self.back_btn)

        # Timer and alert refresh
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.update_refresh)
        self.refresh_timer.start(15000)

        self.card_layout.setSpacing(12)
        self.card_layout.setContentsMargins(10, 10, 10, 10)
        self.card_layout.setSpacing(10)
        self.card_layout.setAlignment(Qt.AlignTop)

        # Load alerts
        self.load_alerts()



    def prefill_new_alert(self):
        trigger_type = self.trigger_selector.currentData()
        preset = self.default_alert_presets.get(trigger_type, {})

        new_alert = {
            "universal_id": f"crypto-{uuid.uuid4().hex[:6]}",
            "trigger_type": trigger_type,
            "type": trigger_type,
            "pair": preset.get("pair", "BTC/USDT"),
            "threshold": preset.get("threshold", 0),
            "cooldown": preset.get("cooldown", 300),
            "exchange": "coingecko",
            "active": True,
            "name": f"New {trigger_type.replace('_', ' ').title()}",
            "poll_interval": 60,
            "notify": ["gui"]
        }

        if "change_percent" in preset:
            new_alert["change_percent"] = preset["change_percent"]
        if "from_asset" in preset:
            new_alert["from_asset"] = preset["from_asset"]
            new_alert["to_asset"] = preset.get("to_asset", "")
            new_alert["from_amount"] = preset.get("from_amount", 0)

        self.alerts.append(new_alert)
        self.save_alerts()
        self.refresh_cards()

    def create_alert_card(self, alert):
        card = QGroupBox(alert.get("name") or f"{alert.get('pair')} | {alert.get('trigger_type').upper()}")
        layout = QVBoxLayout(card)
        layout.addWidget(self.build_alert_summary_bar(alert))

        card.setStyleSheet("""
            QGroupBox {
                background-color: #111;
                border: 1px solid #00aa66;
                border-radius: 6px;
                padding: 10px;
                margin: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                color: #00ff66;
            }
        """)

        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        card.setMaximumWidth(420)
        card.setMinimumWidth(300)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Pair
        pair_input = QComboBox()
        pair_input.setEditable(True)
        pair_input.addItems(self.supported_pairs)
        pair_input.setCurrentText(alert.get("pair", ""))
        layout.addWidget(QLabel("Pair:"))
        layout.addWidget(pair_input)

        # Trigger type (read-only to match spec)
        trigger_label = QLabel(alert.get("trigger_type").replace("_", " ").title())
        trigger_label.setContentsMargins(0, 0, 0, 10)
        trigger_label.setStyleSheet("font-weight: bold; color: #33ff33;")
        layout.addWidget(QLabel("Trigger Type:"))
        trigger_box = QHBoxLayout()
        trigger_box.addWidget(trigger_label)
        layout.addLayout(trigger_box)

        # Threshold
        threshold_input = QLineEdit(str(alert.get("threshold", "")))
        layout.addWidget(QLabel("Threshold:"))
        layout.addWidget(threshold_input)

        # Cooldown
        cooldown_input = QSpinBox()
        cooldown_input.setRange(60, 86400)
        cooldown_input.setValue(alert.get("cooldown", 300))
        layout.addWidget(QLabel("Cooldown (sec):"))
        layout.addWidget(cooldown_input)

        # Active checkbox
        active_checkbox = QCheckBox("Active")
        active_checkbox.setChecked(alert.get("active", True))
        layout.addWidget(active_checkbox)

        # Name
        name_input = QLineEdit(alert.get("name", ""))
        layout.addWidget(QLabel("Alert Name:"))
        layout.addWidget(name_input)

        # Save + Delete buttons
        btn_row = QHBoxLayout()
        save_btn = QPushButton("💾 Save")
        delete_btn = QPushButton("🗑 Delete")

        def save_changes():
            updated = {
                "pair": pair_input.currentText().strip(),
                "threshold": float(threshold_input.text().strip() or "0"),
                "cooldown": cooldown_input.value(),
                "active": active_checkbox.isChecked(),
                "name": name_input.text().strip(),
                "trigger_type": alert.get("trigger_type", "price_above"),
                "type": alert.get("trigger_type", "price_above"),
                "exchange": alert.get("exchange", "coingecko"),
                "poll_interval": 60,
                "notify": ["gui"],
                "universal_id": alert["universal_id"]
            }
            # replace the alert in memory
            for i, a in enumerate(self.alerts):
                if a.get("universal_id") == alert["universal_id"]:
                    self.alerts[i] = updated
                    break
            self.save_alerts()
            self.send_agent_payload(updated, partial=True)
            self.refresh_cards()
            QMessageBox.information(self, "Agent Saved", f"{alert['name']} was pushed to Matrix.")

        def delete_alert():
            self.delete_selected_alert(alert)

        save_btn.clicked.connect(save_changes)
        delete_btn.clicked.connect(delete_alert)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(delete_btn)
        layout.addLayout(btn_row)

        return card

    def build_alert_summary_bar(self, alert):
        from PyQt5.QtWidgets import QLabel, QHBoxLayout, QWidget
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # Status Dot
        status = "🟢" if alert.get("active", True) else "🔴"
        layout.addWidget(QLabel(status))

        # Title (pair + trigger type)
        title = f"{alert.get('pair')} | {alert.get('trigger_type', '').replace('_', ' ').upper()}"
        title_label = QLabel(f"<b>{title}</b>")
        layout.addWidget(title_label)


        # Prices / Conditions
        pair = alert.get("pair", "BTC/USDT")
        price = self.get_price(pair) or 0.0
        layout.addWidget(self._pill(f"{pair.split('/')[0]}  ${price:,.2f}"))

        if alert.get("trigger_type", "").startswith("price_change"):
            layout.addWidget(self._pill(f"Δ {alert.get('change_percent', '?')}%"))

        if alert.get("trigger_type") == "asset_conversion":
            from_amt = alert.get("from_amount", "?")
            to = alert.get("to_asset", "?")
            layout.addWidget(self._pill(f"c.c. {from_amt} → {to}"))

        layout.addStretch()
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        bar.setMinimumWidth(300)

        layout.addStretch()
        return bar

    def _pill(self, text):
        label = QLabel(text)
        label.setStyleSheet("""
            QLabel {
                background-color: #444;
                color: #fff;
                border-radius: 8px;
                padding: 2px 8px;
                font-weight: bold;
            }
        """)
        return label

    def update_trigger_mode_fields(self, mode):
        if not hasattr(self, "threshold_input"):
            return  # early out if fields not initialized yet

        mode = (mode or "").lower().strip()

        self.threshold_input.setEnabled(
            any(x in mode for x in ["above", "below", "conversion"])
        )
        if hasattr(self, "change_percent_input"):
            self.change_percent_input.setEnabled("price_change" in mode)
        if hasattr(self, "change_absolute_input"):
            self.change_absolute_input.setEnabled("price_delta" in mode)
        if hasattr(self, "from_asset_input"):
            self.from_asset_input.setEnabled("asset_conversion" in mode)
        if hasattr(self, "to_asset_input"):
            self.to_asset_input.setEnabled("asset_conversion" in mode)
        if hasattr(self, "from_amount_input"):
            self.from_amount_input.setEnabled("asset_conversion" in mode)

    def handle_back(self):
        if self.back_callback:
            self.back_callback()

    def load_alerts(self):
        if os.path.exists(self.alert_path):
            with open(self.alert_path) as f:
                self.alerts = json.load(f)
        else:
            self.alerts = []
        self.refresh_cards()
        self.reissue_pending_deletes()
        self.verify_agent_status()

    def update_refresh(self):
        self.update_price_display()
        self.refresh_cards()

    def refresh_cards(self):
        # Clear previous cards
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self.alerts:
            placeholder = QLabel("No alerts yet. Select an alert type and click ➕ Add to get started.")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: gray; font-style: italic; padding: 20px;")
            self.card_layout.addWidget(placeholder)
            return

        for alert in self.alerts:
            self.card_layout.addWidget(self.create_alert_card(alert))


    def load_alert_to_form(self, alert):
        self.name_input.setText(alert.get("name", ""))
        self.uid_display.setText(f"Universal ID: {alert.get('universal_id', '--')}")
        self.pair_input.setCurrentText(alert.get("pair", ""))
        self.threshold_input.setText(str(alert.get("threshold", "")))
        self.cooldown_input.setValue(alert.get("cooldown", 300))
        self.change_percent_input.setText(str(alert.get("change_percent", "")))
        self.change_absolute_input.setText(str(alert.get("change_absolute", "")))
        self.from_asset_input.setCurrentText(alert.get("from_asset", ""))
        self.to_asset_input.setCurrentText(alert.get("to_asset", ""))
        self.from_amount_input.setText(str(alert.get("from_amount", "")))
        self.exchange_selector.setCurrentText(alert.get("exchange", "coingecko"))
        self.limit_mode_selector.setCurrentText(alert.get("limit_mode", "forever"))
        self.limit_count_input.setValue(alert.get("activation_limit") or 1)
        self.active_selector.setCurrentIndex(0 if alert.get("active", True) else 1)

        trigger_type = alert.get("trigger_type", "price_change")
        self.trigger_selector.setCurrentIndex(self.trigger_selector.findData(trigger_type))
        self.update_trigger_mode_fields(trigger_type)

    def queue_delete_alert(self, alert):
        uid = alert.get("universal_id")
        if not uid:
            return
        for i, a in enumerate(self.alerts):
            if a.get("universal_id") == uid:
                self.alerts[i]["pending_delete"] = True
                self.alerts[i]["active"] = False
                break
        self.save_alerts()
        self.refresh_cards()
        self.reissue_pending_deletes()
        QMessageBox.information(self, "Delete Pending", f"Alert '{uid}' queued for removal.")


    def format_alert_text(self, alert, current_price):
        threshold = alert.get("threshold")
        cooldown = alert.get("cooldown", 300)
        status_flag = alert.get("swarm_status", "")
        pair = alert.get("pair", "???")
        trigger_type = alert.get("trigger_type", alert.get("type", "?"))
        exchange = alert.get("exchange", "coingecko").capitalize()

        diff = ""
        if threshold is not None and current_price is not None:
            try:
                delta = current_price - threshold
                diff = f" | Δ ${delta:,.2f}"
            except Exception:
                pass

        if alert.get("pending_delete"):
            status = "🟡 Pending Delete"
        elif alert.get("active") is False:
            status = "🔴 Inactive"
        else:
            status = "🟢 Active"

        base = f"{pair} {trigger_type} {threshold} ({cooldown}s){diff} | {status} | {exchange}"

        if status_flag == "missing":
            base = "⚠️ " + base
        elif status_flag == "online":
            base = "✅ " + base

        return base

    def get_alert_color(self, alert, current_price):
        alert_type = alert.get("type")
        threshold = alert.get("threshold")

        if current_price is None or threshold is None:
            return QColor("gray")

        try:
            if alert_type == "price_above" and current_price >= threshold:
                return QColor("red")
            elif alert_type == "price_below" and current_price <= threshold:
                return QColor("red")
            elif abs(current_price - threshold) / threshold < 0.02:
                return QColor("yellow")
            else:
                return QColor("#33ff33")
        except Exception:
            return QColor("gray")



    def add_alert(self):

        try:
            alert = self.build_alert_from_inputs()
            if not alert:
                return

            self.alerts.append(alert)
            self.save_alerts()
            self.send_agent_payload(alert, partial=False)
            self.refresh_cards()

            QMessageBox.information(self, "Alert Created", f"New alert created with ID:\n{alert['universal_id']}")
        except ValueError:
            QMessageBox.critical(self, "Invalid Input", "Please enter a valid numeric threshold.")
        except Exception as e:
            print(f"[ALERT PANEL][ERROR] Failed to add alert: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add alert:\n{e}")

    def verify_agent_status(self):
        for alert in self.alerts:
            uid = alert.get("universal_id")
            if not uid:
                continue

            payload = {
                "handler": "cmd_check_agent_presence",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": uid
                },
                "respond_to": "crypto_gui_1",
                "handler_role": "hive.rpc.route",
                "handler": "cmd_rpc_route",
                "response_handler": "rpc_result_check_agent_presence",
                "response_id": uid + "-presence"
            }

            pkt = self.get_delivery_packet("standard.command.packet")
            pkt.set_data(payload)
            self.send_post(pkt.get_packet())

    def rpc_result_check_agent_presence(self, content, payload):
        uid = content.get("target_universal_id")
        found = content.get("found", False)

        for alert in self.alerts:
            if alert.get("universal_id") == uid:
                alert["swarm_status"] = "online" if found else "missing"
                self.refresh_cards()
                break

    def build_alert_from_inputs(self, existing_uid=None):
        mode = self.trigger_selector.currentData()
        try:
            alert = {
                "name": self.name_input.text().strip(),
                "pair": self.pair_input.currentText().strip(),
                "type": self.trigger_selector.currentData(),
                "threshold": float(self.threshold_input.text().strip()) if mode != "price_change" else 0.0,
                "cooldown": self.cooldown_input.value(),
                "notify": ["gui"],
                "universal_id": existing_uid or f"crypto-{self.pair_input.text().strip().replace('/', '').lower()}-{uuid.uuid4().hex[:6]}",
                "exchange": self.exchange_selector.currentText(),
                "limit_mode": self.limit_mode_selector.currentText(),
                "activation_limit": self.limit_count_input.value() if self.limit_mode_selector.currentText() == "custom" else None,
                "active": self.active_selector.currentText() == "Active",
                "trigger_type": mode,
                "poll_interval": 60,
                "change_percent": float(self.change_percent_input.text()) if mode == "price_change" else None,
                "from_asset": self.from_asset_input.currentText().strip() if mode == "asset_conversion" else None,
                "to_asset": self.to_asset_input.currentText().strip() if mode == "asset_conversion" else None,
                "from_amount": float(self.from_amount_input.text().strip()) if mode == "asset_conversion" else None,
                "change_absolute": float(self.change_absolute_input.text()) if mode == "price_delta" else None,
            }
            return alert
        except ValueError as e:
            QMessageBox.critical(self, "Invalid Input", "Please enter valid numeric values.")
            return None

    def build_agent_config(self, alert):
        return {
            "pair": alert.get("pair"),
            "type": alert.get("trigger_type"),
            "threshold": alert.get("threshold"),
            "cooldown": alert.get("cooldown"),
            "exchange": alert.get("exchange", "coingecko"),
            "limit_mode": alert.get("limit_mode", "forever"),
            "activation_limit": alert.get("activation_limit"),
            "active": alert.get("active", True),
            "trigger_type": alert.get("trigger_type", "price_change"),
            "poll_interval": alert.get("poll_interval", 60),
            "alert_handler":  "cmd_send_alert_msg",
            "alert_role": "hive.alert.send_alert_msg",
        }

    def send_agent_payload(self, alert, partial=False, response_handler="rpc_result_inject_agent"):
        uid = alert.get("universal_id")
        if not uid:
            print("[AGENT][ERROR] Missing universal_id.")
            return

        config = self.build_agent_config(alert)
        if partial:
            config["partial_config"] = True

        agent_packet = {
            "name": "crypto_alert",
            "universal_id": uid,
            "filesystem": {},
            "config": config,
            "source_payload": None
        }

        packet_data = {
            "handler": "cmd_inject_agents",
            "content": {
                "target_universal_id": "matrix",
                "subtree": agent_packet,
                "confirm_response": 1,
                "respond_to": "crypto_gui_1",
                "handler_role": "hive.rpc.route",
                "handler": "cmd_rpc_route",
                "response_handler": response_handler,
                "response_id": uuid.uuid4().hex,
                "push_live_config": partial
            }
        }

        pkt = self.get_delivery_packet("standard.command.packet")
        pkt.set_data(packet_data)
        self.send_post(pkt.get_packet())

    def rpc_result_inject_agent(self, content, payload):
        pass

    def send_post(self, payload):
        if hasattr(self.parent(), "send_post_to_matrix"):
            self.parent().send_post_to_matrix(payload, f"Agent dispatched")
        else:
            print("[ERROR] No connection to send_post_to_matrix")

    def reissue_pending_deletes(self):
        for alert in self.alerts:
            if alert.get("pending_delete"):
                uid = alert.get("universal_id")
                payload = {
                    "target_universal_id": "matrix",
                    "confirm_response": 1,
                    "respond_to": "crypto_gui_1",
                    "handler_role": "hive.rpc.route",
                    "handler": "cmd_rpc_route",
                    "response_handler": "rpc_result_delete_agent_local_confirmed",
                    "response_id": uuid.uuid4().hex,
                    "content": {
                        "target_universal_id": uid
                    }
                }

                packet = self.get_delivery_packet("standard.command.packet")
                packet.set_data({
                    "handler": "cmd_delete_agent",
                    "content": payload
                })

                self.send_post(packet.get_packet())

    def delete_selected_alert(self, alert):
        uid = alert.get("universal_id")
        if not uid:
            print("[DELETE][ERROR] No UID found in alert.")
            return

        # Mark locally
        for i, a in enumerate(self.alerts):
            if a.get("universal_id") == uid:
                self.alerts[i]["pending_delete"] = True
                self.alerts[i]["active"] = False
                break

        self.save_alerts()
        self.refresh_cards()

        # Build and send delete packet
        payload = {
            "target_universal_id": uid,
            "confirm_response": 1,
            "respond_to": "crypto_gui_1",
            "handler_role": "hive.rpc.route",
            "handler": "cmd_rpc_route",
            "response_handler": "rpc_result_delete_agent_local_confirmed",
            "response_id": uuid.uuid4().hex,
        }

        packet = self.get_delivery_packet("standard.command.packet")
        packet.set_data({
            "handler": "cmd_delete_agent",
            "content": payload
        })

        print('Sending Captain Howdy to deal with the good people')

        self.send_post(packet.get_packet())

        QMessageBox.information(self, "Delete Pending", f"Alert '{uid}' queued for removal.")

    #returns confirmation the agent was deleted. it is not physically deleted
    #until the agent is confirmed to be deleted or returns it wasn't found in the swarm
    def rpc_result_delete_agent_local_confirmed(self, content, payload):


        # Handle new format (when "content" wraps details in 'details')
        if isinstance(content, dict):
            uid = str(content.get("target_universal_id") or content.get("details", {}).get("target_universal_id")).strip()

            status = content.get("status", "success")
            error_code = content.get("error_code")
            message = content.get("message", "")
        else:
            print("[ERROR] Invalid content format in delete_agent response")
            return

        if not uid:
            print("[ERROR] No universal_id found in delete confirmation payload.")
            return

        # Search for matching alert
        for i, alert in enumerate(self.alerts):
            if alert.get("universal_id") == uid:
                if status == "success":
                    print(f"[DELETE] Agent {uid} deleted successfully.")
                elif status == "error" and error_code == 99:
                    print(f"[DELETE] Agent {uid} not found — assuming already deleted.")
                else:
                    print(f"[DELETE] Error occurred for {uid}: {message}")
                    return  # Don't delete if it's a real failure unrelated to deletion

                del self.alerts[i]
                self.save_alerts()
                self.refresh_cards()
                return

        # If we somehow didn’t find and delete it in the loop
        self.alerts = [a for a in self.alerts if a.get("universal_id") != uid]
        self.save_alerts()
        self.refresh_cards()
        print(f"[DELETE] Agent {uid} was not found in local alert list.")


    def save_alerts(self):
        try:
            with open(self.alert_path, "w") as f:
                json.dump(self.alerts, f, indent=2)
        except Exception as e:
            print(f"[ALERT PANEL][ERROR] Failed to save alerts: {e}")

    def update_price_display(self):
        pair = self.pair_input.currentText().strip()
        price = self.get_price(pair)
        if price:
            self.price_display.setText(f"Current Price: ${price:,.2f}")
        else:
            self.price_display.setText("Current Price: --")

    def update_price_display(self):
        pass  # fully override it for now, since pair_input is dead

    def get_price(self, pair):
        now = time.time()
        if now - self.price_last_fetch < 15:
            return self.price_cache.get(pair)
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            ids = {
                "BTC/USDT": "bitcoin",
                "ETH/USDT": "ethereum"
            }
            token_id = ids.get(pair.upper())
            if not token_id:
                return None
            resp = requests.get(url, params={"ids": token_id, "vs_currencies": "usd"}, timeout=5)
            if resp.status_code == 200:
                price = resp.json().get(token_id, {}).get("usd")
                if price:
                    self.price_cache[pair] = price
                    self.price_last_fetch = now
                    return price
        except Exception as e:
            print(f"[PRICE][ERROR] Failed to fetch price")
        return None
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=10):
        super(FlowLayout, self).__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.item_list = []

    def addItem(self, item):
        self.item_list.append(item)

    def count(self):
        return len(self.item_list)

    def itemAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super(FlowLayout, self).setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.item_list:
            size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def doLayout(self, rect, test_only):
        x, y = rect.x(), rect.y()
        line_height = 0
        for item in self.item_list:
            wid = item.widget()
            space_x = self.spacing()
            space_y = self.spacing()
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y()