from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QListWidget, QListWidgetItem, QComboBox, QSpinBox, QMessageBox)
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt
import os
import json
import requests
import time
import uuid

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

        self.alert_list = QListWidget()
        self.alert_list.itemClicked.connect(self.load_selected_alert)
        self.layout.addWidget(QLabel("📈 Active Crypto Alerts"))
        self.layout.addWidget(self.alert_list)

        form_layout = QVBoxLayout()

        self.pair_input = QLineEdit("BTC/USDT")
        self.type_selector = QComboBox()
        self.type_selector.addItems(["price_above", "price_below"])
        self.threshold_input = QLineEdit("35000")
        self.cooldown_input = QSpinBox()
        self.cooldown_input.setMinimum(60)
        self.cooldown_input.setMaximum(86400)
        self.cooldown_input.setValue(300)
        self.price_display = QLabel("Current Price: --")

        self.trigger_selector = QComboBox()
        self.trigger_selector.addItems(["price_change", "price_above", "price_below", "price_delta", "asset_conversion"])
        self.trigger_selector.currentTextChanged.connect(self.update_trigger_mode_fields)

        self.change_absolute_input = QLineEdit("1000")
        form_layout.addWidget(QLabel("Δ$ Absolute Change:"))
        form_layout.addWidget(self.change_absolute_input)

        self.change_percent_input = QLineEdit("1.5")
        self.from_asset_input = QLineEdit("BTC")
        self.to_asset_input = QLineEdit("ETH")
        self.from_amount_input = QLineEdit("0.1")

        form_layout.addWidget(QLabel("Pair:"))
        form_layout.addWidget(self.pair_input)
        form_layout.addWidget(self.price_display)

        self.uid_display = QLabel("Universal ID: --")
        form_layout.addWidget(self.uid_display)

        form_layout.addWidget(QLabel("Trigger Type:"))
        form_layout.addWidget(self.trigger_selector)
        form_layout.addWidget(QLabel("Condition:"))
        form_layout.addWidget(self.type_selector)
        form_layout.addWidget(QLabel("Threshold:"))
        form_layout.addWidget(self.threshold_input)
        form_layout.addWidget(QLabel("Cooldown (sec):"))
        form_layout.addWidget(self.cooldown_input)

        form_layout.addWidget(QLabel("Δ% Change:"))
        form_layout.addWidget(self.change_percent_input)
        form_layout.addWidget(QLabel("From Asset:"))
        form_layout.addWidget(self.from_asset_input)
        form_layout.addWidget(QLabel("To Asset:"))
        form_layout.addWidget(self.to_asset_input)
        form_layout.addWidget(QLabel("From Amount:"))
        form_layout.addWidget(self.from_amount_input)

        self.exchange_selector = QComboBox()
        self.exchange_selector.addItems(["coingecko", "binance", "coinbase", "kraken", "bitfinex"])
        form_layout.addWidget(QLabel("Exchange:"))
        form_layout.addWidget(self.exchange_selector)

        self.limit_mode_selector = QComboBox()
        self.limit_mode_selector.addItems(["1", "forever", "custom"])
        self.limit_mode_selector.currentTextChanged.connect(
            lambda mode: self.limit_count_input.setEnabled(mode == "custom")
        )
        form_layout.addWidget(QLabel("Trigger Limit:"))
        form_layout.addWidget(self.limit_mode_selector)

        self.limit_count_input = QSpinBox()
        self.limit_count_input.setMinimum(1)
        self.limit_count_input.setMaximum(999)
        self.limit_count_input.setEnabled(False)
        form_layout.addWidget(self.limit_count_input)

        btn_row = QHBoxLayout()
        self.create_btn = QPushButton("➕ Create Alert")
        self.create_btn.clicked.connect(self.add_alert)
        self.edit_btn = QPushButton("✏️ Update Selected")
        self.edit_btn.clicked.connect(self.edit_selected_alert)
        self.delete_btn = QPushButton("🗑 Delete Selected")
        self.delete_btn.clicked.connect(self.delete_selected_alert)
        self.deactivate_btn = QPushButton("🛑 Deactivate Alert")
        self.deactivate_btn.clicked.connect(self.deactivate_selected_alert)
        self.back_btn = QPushButton("⬅️ Back to Hive")
        self.back_btn.clicked.connect(self.handle_back)

        for btn in [self.deactivate_btn, self.create_btn, self.edit_btn, self.delete_btn, self.back_btn]:
            btn_row.addWidget(btn)

        form_layout.addLayout(btn_row)
        self.layout.addLayout(form_layout)

        self.load_alerts()
        self.update_price_display()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.update_refresh)
        self.refresh_timer.start(15000)
        self.update_trigger_mode_fields(self.trigger_selector.currentText())

    def update_trigger_mode_fields(self, mode):
        self.threshold_input.setEnabled(mode in ["price_above", "price_below", "asset_conversion"])
        self.change_percent_input.setEnabled(mode == "price_change")
        self.from_asset_input.setEnabled(mode == "asset_conversion")
        self.to_asset_input.setEnabled(mode == "asset_conversion")
        self.from_amount_input.setEnabled(mode == "asset_conversion")
        self.change_absolute_input.setEnabled(mode == "price_delta")

    def handle_back(self):
        if self.back_callback:
            self.back_callback()

    def load_alerts(self):
        if os.path.exists(self.alert_path):
            with open(self.alert_path) as f:
                self.alerts = json.load(f)
        else:
            self.alerts = []
        self.refresh_list()
        self.reissue_pending_deletes()
        self.verify_agent_status()

    def update_refresh(self):
        self.update_price_display()
        self.refresh_list()

    def refresh_list(self):
        # Save current selection
        current_index = self.alert_list.currentRow()

        self.alert_list.clear()
        current_price = self.get_price(self.pair_input.text().strip())

        for i, alert in enumerate(self.alerts):
            status_flag = alert.get("swarm_status", "")
            threshold = alert.get("threshold")
            current_price = self.get_price(alert.get("pair", ""))
            delta = (current_price - threshold) if current_price and threshold else None
            diff = f" | Δ ${delta:,.2f}" if delta is not None else ""

            if alert.get("pending_delete"):
                status = "🟡 Pending Delete"
            elif alert.get("active") is False:
                status = "🔴 Inactive"
            else:
                status = "🟢 Active"


            exchange = alert.get("exchange", "coingecko").capitalize()
            pair = alert.get("pair", "???")
            trigger_type = alert.get("trigger_type", alert.get("type", "?"))
            cooldown = alert.get("cooldown", 300)

            # Build base txt
            txt = f"{pair} {trigger_type} {threshold} ({cooldown}s) {diff} | {status} | {exchange}"

            # Add status flag icon to front
            if status_flag == "missing":
                txt = "⚠️ " + txt
            elif status_flag == "online":
                txt = "✅ " + txt

            item = QListWidgetItem(txt)

            # Optional: tooltip
            if status_flag == "missing":
                item.setToolTip("Agent not running in swarm")
            elif status_flag == "online":
                item.setToolTip("Agent is verified in swarm")
            else:
                item.setToolTip("Swarm status unknown")

            # Optional: coloring logic (unchanged)
            if current_price:
                if alert["type"] == "price_above" and current_price >= threshold:
                    item.setForeground(QColor("red"))
                elif alert["type"] == "price_below" and current_price <= threshold:
                    item.setForeground(QColor("red"))
                elif abs(current_price - threshold) / threshold < 0.02:
                    item.setForeground(QColor("yellow"))
                else:
                    item.setForeground(QColor("#33ff33"))

            self.alert_list.addItem(item)

            # Optional: alert color rules
            if current_price:
                if alert["type"] == "price_above" and current_price >= threshold:
                    item.setForeground(QColor("red"))
                elif alert["type"] == "price_below" and current_price <= threshold:
                    item.setForeground(QColor("red"))
                elif abs(current_price - threshold) / threshold < 0.02:
                    item.setForeground(QColor("yellow"))
                else:
                    item.setForeground(QColor("#33ff33"))

            status_flag = alert.get("swarm_status", "")
            if status_flag == "missing":
                txt += " ⚠️ Not Running"
            elif status_flag == "online":
                txt += " ✅ Running"

            self.alert_list.addItem(item)

        # Restore previous selection
        if 0 <= current_index < self.alert_list.count():
            self.alert_list.setCurrentRow(current_index)
            self.selected_index = current_index



    def add_alert(self):
        try:
            pair = self.pair_input.text().strip()
            threshold = float(self.threshold_input.text().strip())
            cooldown = self.cooldown_input.value()
            mode = self.trigger_selector.currentText()
            alert = {
                "pair": pair,
                "type": self.type_selector.currentText(),
                "threshold": threshold if mode != "price_change" else None,
                "cooldown": cooldown,
                "notify": ["gui"],
                "universal_id": f"crypto-{pair.replace('/', '').lower()}-{uuid.uuid4().hex[:6]}",
                "dispatched": None,
                "confirmed": False,
                "exchange": self.exchange_selector.currentText(),
                "limit_mode": self.limit_mode_selector.currentText(),
                "activation_limit": self.limit_count_input.value() if self.limit_mode_selector.currentText() == "custom" else None,
                "active": True,
                "trigger_type": self.trigger_selector.currentText(),
                "poll_interval": 60,
                "change_percent": float(self.change_percent_input.text()) if mode == "price_change" else None,
                "from_asset": self.from_asset_input.text().strip() if mode == "asset_conversion" else None,
                "to_asset": self.to_asset_input.text().strip() if mode == "asset_conversion" else None,
                "from_amount": float(self.from_amount_input.text().strip()) if mode == "asset_conversion" else None,
                "change_absolute": float(self.change_absolute_input.text()) if mode == "price_delta" else None,
            }

            self.alerts.append(alert)
            self.save_alerts()
            self.dispatch_agent(alert)  # ✅ immediately dispatch new agent
            self.refresh_list()

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
                self.refresh_list()
                break

    def deactivate_selected_alert(self):
        selected = self.alert_list.currentRow()
        if selected >= 0:
            self.alerts[selected]["active"] = False
            self.save_alerts()
            self.refresh_list()
            QMessageBox.information(self, "Alert Deactivated", "The selected alert has been deactivated.")

    def edit_selected_alert(self):
        selected = self.alert_list.currentRow()
        mode = self.trigger_selector.currentText()

        if selected < 0 or selected >= len(self.alerts):
            QMessageBox.warning(self, "No Selection", "Please select an alert from the list before updating.")
            return

        try:
            # Preserve immutable values
            original = self.alerts[selected]
            updated_alert = {
                "pair": self.pair_input.text().strip(),
                "type": self.type_selector.currentText(),
                "threshold": float(self.threshold_input.text().strip()),
                "cooldown": self.cooldown_input.value(),
                "notify": ["gui"],
                "universal_id": original.get("universal_id"),
                "exchange": self.exchange_selector.currentText(),
                "limit_mode": self.limit_mode_selector.currentText(),
                "activation_limit": self.limit_count_input.value() if self.limit_mode_selector.currentText() == "custom" else None,
                "active": original.get("active", True),
                "trigger_type": mode,
                "poll_interval": 60,
                "change_percent": float(self.change_percent_input.text()) if mode == "price_change" else None,
                "from_asset": self.from_asset_input.text().strip() if mode == "asset_conversion" else None,
                "to_asset": self.to_asset_input.text().strip() if mode == "asset_conversion" else None,
                "from_amount": float(self.from_amount_input.text().strip()) if mode == "asset_conversion" else None,
                "change_absolute": float(self.change_absolute_input.text()) if mode == "price_delta" else None,
            }

            # Replace and persist
            self.alerts[selected] = updated_alert
            self.save_alerts()
            self.refresh_list()

            # Dispatch if still active
            if updated_alert["active"]:
                self.update_agent(updated_alert)

            QMessageBox.information(self, "Success", "Alert updated successfully.")
        except ValueError:
            QMessageBox.critical(self, "Invalid Input", "Please enter a valid numeric threshold.")
        except Exception as e:
            print(f"[ALERT PANEL][ERROR] Failed to update alert: {e}")
            QMessageBox.critical(self, "Error", f"Failed to update alert:\n{e}")

    def dispatch_agent(self, alert):

        uid = alert.get("universal_id")
        if not uid:
            print("[DISPATCH][ERROR] Missing universal_id in alert. Aborting dispatch.")
            return

        uid = alert["universal_id"]

        agent_packet = {
            "name": "crypto_alert",
            "universal_id": uid,
            "filesystem": {},
            "config": {
                "pair": alert.get("pair"),
                "type": alert.get("type"),
                "threshold": alert.get("threshold"),
                "cooldown": alert.get("cooldown"),
                "exchange": alert.get("exchange", "coingecko"),
                "limit_mode": alert.get("limit_mode", "forever"),
                "activation_limit": alert.get("activation_limit"),
                "active": alert.get("active", True),
                "trigger_type": alert.get("trigger_type", "price_change"),
                "poll_interval": alert.get("poll_interval", 60)
            },
            "source_payload": None  # Optional code payload for spawn
        }

        payload =  {
                "target_universal_id": "matrix",
                "subtree": agent_packet,
                "confirm_response": 1,
                "respond_to": "crypto_gui_1",
                "handler_role": "hive.rpc.route",  #the handlers role in the hive
                "handler": "cmd_rpc_route",   #most likely a websocket to return the packet
                "response_handler": "rpc_result_inject_agent", #waiting at the gui to receive packet
                "response_id": uuid.uuid4().hex
            }

        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({
            "handler": "cmd_inject_agents",
            "content": payload
        })
        #pk1.get_packet(),
        #print(pk1.get_packet())

        payload=pk1.get_packet()
        self.send_post(payload)

    def update_agent(self, alert):

        uid = alert.get("universal_id")
        if not uid:
            print("[UPDATE][ERROR] Missing universal_id. Cannot proceed.")
            return

        config_payload = {
            "pair": alert.get("pair"),
            "type": alert.get("type"),
            "threshold": alert.get("threshold"),
            "cooldown": alert.get("cooldown"),
            "exchange": alert.get("exchange", "coingecko"),
            "limit_mode": alert.get("limit_mode", "forever"),
            "activation_limit": alert.get("activation_limit"),
            "active": alert.get("active", True),
            "trigger_type": alert.get("trigger_type", "price_change"),
            "poll_interval": alert.get("poll_interval", 60)
        }

        payload = {
            "target_universal_id": uid,
            "push_live_config": True,
            "config": config_payload,
            "confirm_response": 1,
            "respond_to": "crypto_gui_1",
            "handler_role": "hive.rpc.route",
            "handler": "cmd_rpc_route",
            "response_handler": "rpc_result_update_agent",
            "response_id": uuid.uuid4().hex
        }

        pkt = self.get_delivery_packet("standard.command.packet")
        pkt.set_data({
            "handler": "cmd_update_agent",
            "content": payload
        })

        self.send_post(pkt.get_packet())

    def rpc_result_inject_agent(self, content, payload):
        print("what u")

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

    def delete_selected_alert(self):
        selected = self.alert_list.currentRow()
        if selected < 0:
            return

        uid = self.alerts[selected].get("universal_id")
        if uid:
            self.alerts[selected]["pending_delete"] = True
            self.alerts[selected]["active"] = False
            self.save_alerts()
            self.refresh_list()

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

            self.send_post(packet.get_packet())

            # Cosmetic dialog only
            QMessageBox.information(self, "Delete Pending", "Awaiting confirmation from Matrix before deletion.")


    def rpc_result_delete_agent_local_confirmed(self, content, payload):
        uid = content.get("target_universal_id")
        for i, alert in enumerate(self.alerts):
            if alert.get("universal_id") == uid:
                del self.alerts[i]
                self.save_alerts()
                self.refresh_list()
                break


    def load_selected_alert(self):
        selected = self.alert_list.currentRow()
        print(f"[DEBUG] Selected row: {selected}")
        if selected >= 0:
            alert = self.alerts[selected]
            print(f"[DEBUG] Loaded alert: {alert}")
            uid = alert.get("universal_id", "--")
            self.uid_display.setText(f"Universal ID: {uid}")
            self.uid_display.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.pair_input.setText(alert.get("pair", ""))
            self.threshold_input.setText(str(alert.get("threshold", "")))
            self.cooldown_input.setValue(alert.get("cooldown", 300))
            self.trigger_selector.setCurrentText(alert.get("trigger_type", "price_change"))
            self.change_percent_input.setText(str(alert.get("change_percent", "")))
            self.change_absolute_input.setText(str(alert.get("change_absolute", "")))
            self.from_asset_input.setText(alert.get("from_asset", ""))
            self.to_asset_input.setText(alert.get("to_asset", ""))
            self.from_amount_input.setText(str(alert.get("from_amount", "")))
            self.exchange_selector.setCurrentText(alert.get("exchange", "coingecko"))
            self.limit_mode_selector.setCurrentText(alert.get("limit_mode", "forever"))
            self.limit_count_input.setValue(alert.get("activation_limit") or 1)
            index = self.type_selector.findText(alert.get("type", "price_above"))
            if index != -1:
                self.type_selector.setCurrentIndex(index)

    def save_alerts(self):
        try:
            with open(self.alert_path, "w") as f:
                json.dump(self.alerts, f, indent=2)
        except Exception as e:
            print(f"[ALERT PANEL][ERROR] Failed to save alerts: {e}")

    def update_price_display(self):
        pair = self.pair_input.text().strip()
        price = self.get_price(pair)
        if price:
            self.price_display.setText(f"Current Price: ${price:,.2f}")
        else:
            self.price_display.setText("Current Price: --")

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
