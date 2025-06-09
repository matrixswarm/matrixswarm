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

        self.trigger_type_options = [
            ("Price Change - Above", "price_change_above"),
            ("Price Change - Below", "price_change_below"),
            ("Price Delta - Above", "price_delta_above"),
            ("Price Delta - Below", "price_delta_below"),
            ("Price Above", "price_above"),
            ("Price Below", "price_below"),
            ("Asset Conversion", "asset_conversion")
        ]

        form_layout = QVBoxLayout()

        self.pair_input = QLineEdit("BTC/USDT")

        self.threshold_input = QLineEdit("35000")
        self.cooldown_input = QSpinBox()
        self.cooldown_input.setMinimum(60)
        self.cooldown_input.setMaximum(86400)
        self.cooldown_input.setValue(300)
        self.price_display = QLabel("Current Price: --")



        # === Trigger dropdown ===
        self.trigger_selector = QComboBox()
        for label, value in self.trigger_type_options:
            self.trigger_selector.addItem(label, value)

        self.trigger_selector.currentIndexChanged.connect(
            lambda _: self.update_trigger_mode_fields(self.trigger_selector.currentData())
        )

        # 🔐 Assert trap to confirm the dropdown isn't overwritten later
        if self.trigger_selector.count() == 0:
            print("[DEBUG][CRITICAL] trigger_selector is EMPTY — possible overwrite or missing addItem() calls.")
        else:
            print(f"[DEBUG] trigger_selector initialized with {self.trigger_selector.count()} options.")


        self.active_selector = QComboBox()
        self.active_selector.addItems(["Active", "Inactive"])
        form_layout.addWidget(QLabel("Status:"))
        form_layout.addWidget(self.active_selector)

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

        self.back_btn = QPushButton("⬅️ Back to Hive")
        self.back_btn.clicked.connect(self.handle_back)

        for btn in [self.create_btn, self.edit_btn, self.delete_btn, self.back_btn]:
            btn_row.addWidget(btn)

        form_layout.addLayout(btn_row)
        self.layout.addLayout(form_layout)

        self.load_alerts()
        self.update_price_display()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.update_refresh)
        self.refresh_timer.start(15000)
        self.update_trigger_mode_fields(self.trigger_selector.currentText())

    #changes the activate deactivate button on alert selection
    def toggle_alert_activation(self):
        selected = self.alert_list.currentRow()
        if selected < 0:
            return

        alert = self.alerts[selected]
        if alert.get("active", True):
            alert["active"] = False
            QMessageBox.information(self, "Alert Deactivated", "The selected alert has been deactivated.")
        else:
            alert["active"] = True
            alert["pending_delete"] = False
            QMessageBox.information(self, "Alert Reactivated", "The selected alert has been reactivated.")

        self.save_alerts()
        self.refresh_list()

    def update_trigger_mode_fields(self, mode):
        mode = (mode or "").lower().strip()

        self.threshold_input.setEnabled(
            any(x in mode for x in ["above", "below", "conversion"])
        )
        self.change_percent_input.setEnabled("price_change" in mode)
        self.change_absolute_input.setEnabled("price_delta" in mode)
        self.from_asset_input.setEnabled("asset_conversion" in mode)
        self.to_asset_input.setEnabled("asset_conversion" in mode)
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
        self.refresh_list()
        self.reissue_pending_deletes()
        self.verify_agent_status()

    def update_refresh(self):
        self.update_price_display()
        self.refresh_list()

    def refresh_list(self):
        current_index = self.alert_list.currentRow()
        self.alert_list.clear()

        for alert in self.alerts:
            current_price = self.get_price(alert.get("pair", ""))
            txt = self.format_alert_text(alert, current_price)

            item = QListWidgetItem(txt)
            item.setForeground(self.get_alert_color(alert, current_price))

            swarm_status = alert.get("swarm_status", "")
            if swarm_status == "missing":
                item.setToolTip("Agent not running in swarm")
            elif swarm_status == "online":
                item.setToolTip("Agent is verified in swarm")
            else:
                item.setToolTip("Swarm status unknown")

            self.alert_list.addItem(item)

        if 0 <= current_index < self.alert_list.count():
            self.alert_list.setCurrentRow(current_index)
            self.selected_index = current_index


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
            self.refresh_list()

            QMessageBox.information(self, "Alert Created", f"New alert created with ID:\n{alert['universal_id']}")
        except ValueError:
            QMessageBox.critical(self, "Invalid Input", "Please enter a valid numeric threshold.")
        except Exception as e:
            print(f"[ALERT PANEL][ERROR] Failed to add alert: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add alert:\n{e}")

    def edit_selected_alert(self):
        try:
            selected = self.alert_list.currentRow()
            if selected < 0 or selected >= len(self.alerts):
                QMessageBox.warning(self, "No Selection", "Please select an alert from the list before updating.")
                return

            existing_uid = self.alerts[selected].get("universal_id")
            alert = self.build_alert_from_inputs(existing_uid=existing_uid)
            if not alert:
                return

            self.alerts[selected] = alert
            self.save_alerts()
            self.refresh_list()

            if not alert.get("pending_delete", False):
                self.send_agent_payload(alert, partial=True, response_handler="rpc_result_update_agent")

            QMessageBox.information(self, "Success", "Alert updated successfully.")
        except ValueError:
            QMessageBox.critical(self, "Invalid Input", "Please enter a valid numeric threshold.")
        except Exception as e:
            print(f"[ALERT PANEL][ERROR] Failed to update alert: {e}")
            QMessageBox.critical(self, "Error", f"Failed to update alert:\n{e}")


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

    def build_alert_from_inputs(self, existing_uid=None):
        mode = self.trigger_selector.currentData()
        try:
            alert = {
                "pair": self.pair_input.text().strip(),
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
                "from_asset": self.from_asset_input.text().strip() if mode == "asset_conversion" else None,
                "to_asset": self.to_asset_input.text().strip() if mode == "asset_conversion" else None,
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

    #returns confirmation the agent was deleted. it is not physically deleted
    #until the agent is confirmed to be deleted or returns it wasn't found in the swarm
    def rpc_result_delete_agent_local_confirmed(self, content, payload):
        uid = None

        # Handle new format (when "content" wraps details in 'details')
        if isinstance(content, dict):
            uid = content.get("target_universal_id") or content.get("details", {}).get("target_universal_id")
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
                self.refresh_list()
                return

        print(f"[DELETE] Agent {uid} was not found in local alert list.")


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
            self.trigger_selector.setCurrentIndex(
                self.trigger_selector.findData(alert.get("trigger_type", "price_change"))
            )
            mode = self.trigger_selector.currentData()
            self.update_trigger_mode_fields(mode)
            self.change_percent_input.setText(str(alert.get("change_percent", "")))
            self.change_absolute_input.setText(str(alert.get("change_absolute", "")))
            self.from_asset_input.setText(alert.get("from_asset", ""))
            self.to_asset_input.setText(alert.get("to_asset", ""))
            self.from_amount_input.setText(str(alert.get("from_amount", "")))
            self.exchange_selector.setCurrentText(alert.get("exchange", "coingecko"))
            self.limit_mode_selector.setCurrentText(alert.get("limit_mode", "forever"))
            self.limit_count_input.setValue(alert.get("activation_limit") or 1)
            #if index != -1:
            #    self.type_selector.setCurrentIndex(index)
            status_index = 0 if alert.get("active", True) else 1
            self.active_selector.setCurrentIndex(status_index)

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
