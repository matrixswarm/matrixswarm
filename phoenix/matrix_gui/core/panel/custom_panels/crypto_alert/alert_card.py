# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals

import math
import re
import time
import uuid
from typing import Dict
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame

class AlertCard(QWidget):
    changed = pyqtSignal()
    """
    Visual container for a single crypto alert, Commander Edition.
    Includes:
      - Full trigger config (pair, type, thresholds)
      - Per-alert toggles (active, alert_enabled, stream_enabled)
      - Trigger limit
      - Boiler display module
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("alertCard")

        # live price state
        self._last_price = None
        self._last_ts = None
        self._prev_price = None
        self._conv_from_price = None
        self._conv_to_price = None

        # boiler style
        self._boiler_style = "Clean Cockpit"
        self.alert_id = uuid.uuid4().hex
        self._live = {}
        self._runtime = {}
        self._draft = False

        self._build_ui()
        for widget in self.findChildren(QLineEdit):
            widget.textEdited.connect(self.changed.emit)
        for widget in self.findChildren(QComboBox):
            widget.currentTextChanged.connect(self.changed.emit)
        for widget in self.findChildren(QCheckBox):
            widget.toggled.connect(self.changed.emit)

    # -------------------------------------------------------------------
    # UI BUILD
    # -------------------------------------------------------------------
    def _build_ui(self):
        self.setStyleSheet("""
            QFrame#alertFrame {
                background-color: #080808;
                border: 2px solid #b200ff;
                border-radius: 12px;
                margin: 6px;
                padding: 8px;
            }
            QFrame#alertFrame:hover {
                border: 2px solid #ff36ff;
                background-color: #120012;
            }
            QLabel {
                color: #d27dff;
                font-family: Consolas;
                font-size: 13px;
            }
            QLineEdit, QComboBox {
                background: #000;
                color: #ffb3ff;
                border: 1px solid #cc00ff;
                border-radius: 4px;
                padding: 3px 6px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #ff55ff;
                background-color: #1a001a;
            }
            QCheckBox {
                color: #ff99ff;
            }
            QPushButton.deleteBtn {
                color: #ff66cc;
                background: transparent;
                border: none;
                font-size: 15px;
            }
            QPushButton.deleteBtn:hover {
                color: #ff99ee;
            }
            QLabel.boilerLabel {
                color: #ffd6ff;
                font-family: Consolas;
            }
        """)

        frame = QFrame(self)
        frame.setObjectName("alertFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setFrameShadow(QFrame.Shadow.Raised)
        frame.setLineWidth(2)

        root = QVBoxLayout(frame)
        outer = QVBoxLayout(self)
        outer.addWidget(frame)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # -------------------------------------------------------
        # Header + delete button
        hdr = QHBoxLayout()
        self.header_label = QLabel("Alert")
        self.header_label.setTextFormat(Qt.TextFormat.PlainText)
        hdr.addWidget(self.header_label)
        hdr.addStretch()

        self.delete_btn = QPushButton("✕")
        self.delete_btn.setObjectName("deleteBtn")
        self.delete_btn.setFixedSize(26, 26)
        hdr.addWidget(self.delete_btn)

        root.addLayout(hdr)
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Watch name (optional)")
        self.label_edit.setMaxLength(100)
        root.addWidget(self.label_edit)

        # -------------------------------------------------------
        # Pair
        pair_row = QHBoxLayout()
        pair_row.addWidget(QLabel("Pair:"))
        self.pair_edit = QLineEdit("BTC/USDT")
        pair_row.addWidget(self.pair_edit)
        wrap = QWidget()
        wrap.setLayout(pair_row)
        root.addWidget(wrap)

        # -------------------------------------------------------
        # Trigger type
        trig_row = QHBoxLayout()
        trig_row.addWidget(QLabel("Trigger:"))
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems([
            "price_above",
            "price_below",
            "price_change_above",
            "price_change_below",
            "price_delta_above",
            "price_delta_below",
            "asset_conversion",
            "wallet_change",
        ])
        trig_row.addWidget(self.trigger_combo)
        wrap = QWidget()
        wrap.setLayout(trig_row)
        root.addWidget(wrap)

        self.rule_help = QLabel()
        self.rule_help.setWordWrap(True)
        root.addWidget(self.rule_help)

        # -------------------------------------------------------
        # Main threshold
        thresh_row = QHBoxLayout()
        self.threshold_label = QLabel("Alert price:")
        thresh_row.addWidget(self.threshold_label)
        self.threshold_edit = QLineEdit("0")
        self.threshold_edit.setPlaceholderText("Enter the target price")
        thresh_row.addWidget(self.threshold_edit)
        self.threshold_wrap = QWidget()
        self.threshold_wrap.setLayout(thresh_row)
        root.addWidget(self.threshold_wrap)

        # -------------------------------------------------------
        # Percent change
        pct_row = QHBoxLayout()
        self.pct_label = QLabel("Move (%):")
        pct_row.addWidget(self.pct_label)
        self.pct_edit = QLineEdit("")
        pct_row.addWidget(self.pct_edit)
        self.pct_wrap = QWidget()
        self.pct_wrap.setLayout(pct_row)
        root.addWidget(self.pct_wrap)

        # -------------------------------------------------------
        # Absolute delta
        delta_row = QHBoxLayout()
        self.delta_label = QLabel("Move (quote units):")
        delta_row.addWidget(self.delta_label)
        self.delta_edit = QLineEdit("")
        delta_row.addWidget(self.delta_edit)
        self.delta_wrap = QWidget()
        self.delta_wrap.setLayout(delta_row)
        root.addWidget(self.delta_wrap)

        # -------------------------------------------------------
        # Asset conversion fields
        self.conv_wrap = QWidget()
        conv_layout = QVBoxLayout(self.conv_wrap)
        conv_layout.setContentsMargins(0, 0, 0, 0)
        conv_layout.setSpacing(4)

        r = QHBoxLayout()
        r.addWidget(QLabel("From Asset:"))
        self.from_asset_edit = QLineEdit("BTC")
        r.addWidget(self.from_asset_edit)
        conv_layout.addLayout(r)

        r = QHBoxLayout()
        r.addWidget(QLabel("To Asset:"))
        self.to_asset_edit = QLineEdit("ETH")
        r.addWidget(self.to_asset_edit)
        conv_layout.addLayout(r)

        r = QHBoxLayout()
        self.from_amount_label = QLabel("Source amount:")
        r.addWidget(self.from_amount_label)
        self.from_amount_edit = QLineEdit("0.1")
        r.addWidget(self.from_amount_edit)
        conv_layout.addLayout(r)

        root.addWidget(self.conv_wrap)
        self.wallet_wrap = QWidget()
        wallet_layout = QVBoxLayout(self.wallet_wrap)
        wallet_layout.addWidget(QLabel("Bitcoin mainnet public address:"))
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("bc1… / 1… / 3…")
        wallet_layout.addWidget(self.address_edit)
        wallet_layout.addWidget(QLabel("Check interval (seconds, minimum 30):"))
        self.poll_edit = QLineEdit("60")
        wallet_layout.addWidget(self.poll_edit)
        root.addWidget(self.wallet_wrap)

        # -------------------------------------------------------
        # Per-alert toggles (NEW)
        self.active_chk = QCheckBox("Active")
        self.active_chk.setChecked(True)

        self.alert_enabled_chk = QCheckBox("Alert Enabled")
        self.alert_enabled_chk.setChecked(True)

        self.stream_enabled_chk = QCheckBox("Stream Enabled")
        self.stream_enabled_chk.setChecked(True)

        toggles = QHBoxLayout()
        toggles.addWidget(self.active_chk)
        toggles.addWidget(self.alert_enabled_chk)
        toggles.addWidget(self.stream_enabled_chk)

        toggle_wrap = QWidget()
        toggle_wrap.setLayout(toggles)
        root.addWidget(toggle_wrap)

        # -------------------------------------------------------
        # Trigger limit
        tlim_row = QHBoxLayout()
        tlim_row.addWidget(QLabel("Trigger Limit (0 = unlimited):"))
        self.trigger_limit_edit = QLineEdit("0")
        tlim_row.addWidget(self.trigger_limit_edit)
        wrap = QWidget()
        wrap.setLayout(tlim_row)
        root.addWidget(wrap)
        cooldown_row = QHBoxLayout()
        cooldown_row.addWidget(QLabel("Cooldown (seconds):"))
        self.cooldown_edit = QLineEdit("60")
        cooldown_row.addWidget(self.cooldown_edit)
        root.addLayout(cooldown_row)

        # -------------------------------------------------------
        # Boiler display (unchanged)
        self.boiler_frame = QWidget()
        b = QVBoxLayout(self.boiler_frame)
        b.setContentsMargins(6, 6, 6, 6)
        b.setSpacing(2)

        self.boiler_label = QLabel("")
        self.boiler_label.setTextFormat(Qt.TextFormat.PlainText)
        self.boiler_label.setObjectName("boilerLabel")
        self.boiler_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.boiler_label.setWordWrap(True)
        b.addWidget(self.boiler_label)
        root.addWidget(self.boiler_frame)

        # Hide/show dynamic fields
        self.trigger_combo.currentTextChanged.connect(self._update_field_visibility)
        self._update_field_visibility()

        # clicking outside inputs toggles Active
        # Only explicit controls change whether a watch is active.

        # Force stable minimum size so cards never collapse or flicker
        self.setMinimumHeight(360)
        self.setMinimumWidth(350)
        self.setMaximumWidth(460)
        self.setAutoFillBackground(True)



    # -------------------------------------------------------------------
    # FIELD VISIBILITY
    # -------------------------------------------------------------------
    def _update_field_visibility(self):
        t = self.trigger_combo.currentText()
        self.pct_wrap.setVisible("price_change" in t)
        self.delta_wrap.setVisible("price_delta" in t)
        self.conv_wrap.setVisible("asset_conversion" in t)
        self.wallet_wrap.setVisible(t == "wallet_change")
        self.pair_edit.setEnabled(t not in ("wallet_change", "asset_conversion"))
        self.threshold_wrap.setVisible(t in ("price_above", "price_below", "asset_conversion"))
        pair = self.pair_edit.text().strip().upper()
        parts = pair.split("/", 1)
        base, quote = (parts[0], parts[1]) if len(parts) == 2 else ("asset", "quote")
        if t == "asset_conversion":
            source = self.from_asset_edit.text().strip().upper() or "source asset"
            target = self.to_asset_edit.text().strip().upper() or "target asset"
            self.from_amount_label.setText(f"Amount of {source}:")
            self.threshold_label.setText(f"Alert when conversion reaches ({target}):")
            self.threshold_edit.setPlaceholderText(f"Target amount in {target}")
        elif quote == "USDT":
            self.threshold_label.setText("Alert price (USDT):")
            self.threshold_edit.setPlaceholderText("Example: 78000")
        else:
            self.threshold_label.setText(f"Alert ratio ({quote} per {base}):")
            self.threshold_edit.setPlaceholderText(f"Example: 30 {quote} per {base}")
        self.pct_label.setText(f"Move from baseline (%):")
        self.delta_label.setText(f"Move from baseline ({quote}):")
        hints = {
            "wallet_change": "Alerts on confirmed balance or transaction-count changes. First lookup sets the baseline.",
            "asset_conversion": "Alert when the source amount is worth at least the threshold in the target asset.",
            "price_above": "Alert at or above the threshold; rearm after falling below it.",
            "price_below": "Alert at or below the threshold; rearm after rising above it.",
        }
        self.rule_help.setText(hints.get(t, "Change since this watch was armed; the baseline resets after each alert."))

        pair = self.pair_edit.text().strip()
        if t == "asset_conversion":
            source = self.from_asset_edit.text().strip().upper() or "Source"
            target = self.to_asset_edit.text().strip().upper() or "Target"
            pair = f"{source}/{target}"
        self.header_label.setText(f"{pair or 'Pair'} · {t}")


    # -------------------------------------------------------------------
    # DICT <-> CARD
    # -------------------------------------------------------------------

    def to_dict(self) -> Dict:
        """Match EXACT structure backend Commander Edition expects."""
        t = self.trigger_combo.currentText()

        d = {
            "id": self.alert_id,
            "label": self.label_edit.text().strip(),
            "pair": self.pair_edit.text().strip(),
            "trigger_type": t,
            "threshold": self.threshold_edit.text().strip(),
            "active": self.active_chk.isChecked(),
            "alert_enabled": self.alert_enabled_chk.isChecked(),
            "stream_enabled": self.stream_enabled_chk.isChecked(),
            "trigger_limit": self.trigger_limit_edit.text().strip(),
            "cooldown_sec": self.cooldown_edit.text().strip(),
        }

        # percent change
        if "price_change" in t:
            d["change_percent"] = self.pct_edit.text().strip()

        # absolute delta
        if "price_delta" in t:
            d["change_absolute"] = self.delta_edit.text().strip()

        # conversion
        if t == "asset_conversion":
            d["from_asset"] = self.from_asset_edit.text().strip()
            d["to_asset"] = self.to_asset_edit.text().strip()
            d["from_amount"] = self.from_amount_edit.text().strip()
        if t == "wallet_change":
            d["address"] = self.address_edit.text().strip()
            d["poll_interval"] = self.poll_edit.text().strip()

        return d

    @staticmethod
    def _valid_number(widget, label, minimum=0.0, maximum=1e18, whole=False):
        text = widget.text().strip()
        if not text:
            return f"{label} is required.", widget
        try:
            value = float(text)
        except (TypeError, ValueError, OverflowError):
            return f"{label} must be a number.", widget
        if not math.isfinite(value) or not minimum <= value <= maximum:
            return f"{label} must be between {minimum:g} and {maximum:g}.", widget
        if whole and not value.is_integer():
            return f"{label} must be a whole number.", widget
        return None

    def validation_error(self):
        """Return a concise local validation error and its input widget."""
        trigger = self.trigger_combo.currentText()
        common = (
            self._valid_number(self.trigger_limit_edit, "Trigger limit", 0, 9_999_999, whole=True)
            or self._valid_number(self.cooldown_edit, "Cooldown", 0, 86_400)
        )
        if common:
            return common

        if trigger == "wallet_change":
            address = self.address_edit.text().strip()
            if not re.fullmatch(r"(?:[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[ac-hj-np-z02-9]{11,87})", address):
                return "Enter a Bitcoin mainnet public address (1…, 3…, or bc1…).", self.address_edit
            return self._valid_number(self.poll_edit, "Check interval", 30, 3600)

        if trigger == "asset_conversion":
            for label, widget in (("From asset", self.from_asset_edit),
                                  ("To asset", self.to_asset_edit)):
                if not re.fullmatch(r"[A-Za-z0-9]{2,16}", widget.text().strip()):
                    return f"{label} must be a symbol such as BTC or ETH.", widget
            return (
                self._valid_number(self.from_amount_edit, "Source amount", 1e-12)
                or self._valid_number(self.threshold_edit, "Conversion target", 1e-12)
            )

        if not re.fullmatch(r"[A-Za-z0-9]{2,16}/[A-Za-z0-9]{2,16}", self.pair_edit.text().strip()):
            return "Use a pair such as BTC/USDT or BTC/ETH.", self.pair_edit
        if trigger.startswith("price_change"):
            return self._valid_number(self.pct_edit, "Percent move", 1e-12)
        if trigger.startswith("price_delta"):
            return self._valid_number(self.delta_edit, "Price move", 1e-12)
        return self._valid_number(self.threshold_edit, "Alert price", 1e-12)

    def from_dict(self, alert: Dict):
        """Populate card fields from backend config."""
        self.alert_id = alert.get("id") or uuid.uuid4().hex
        self.label_edit.setText(alert.get("label", ""))
        self.address_edit.setText(alert.get("address", ""))
        self.poll_edit.setText(str(alert.get("poll_interval", 60)))
        self.cooldown_edit.setText(str(alert.get("cooldown_sec", 60)))
        self.pair_edit.setText(alert.get("pair", "BTC/USDT"))

        ttype = alert.get("trigger_type", "price_above")
        self.trigger_combo.setCurrentText(ttype)

        self.threshold_edit.setText(str(alert.get("threshold", 0)))
        self.active_chk.setChecked(alert.get("active", True))
        self.alert_enabled_chk.setChecked(alert.get("alert_enabled", True))
        self.stream_enabled_chk.setChecked(alert.get("stream_enabled", True))

        self.trigger_limit_edit.setText(str(alert.get("trigger_limit", 0)))

        self.pct_edit.setText(str(alert.get("change_percent", "")))
        self.delta_edit.setText(str(alert.get("change_absolute", "")))
        self.from_asset_edit.setText(alert.get("from_asset", "BTC"))
        self.to_asset_edit.setText(alert.get("to_asset", "ETH"))
        self.from_amount_edit.setText(str(alert.get("from_amount", 0.1)))

        self._update_field_visibility()

    # -------------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------------
    def _safe_float(self, txt: str, default: float = 0.0) -> float:
        try:
            txt = (txt or "").replace(",", "").strip()
            if not txt:
                return default
            return float(txt)
        except Exception:
            return default

    # -------------------------------------------------------------------
    # BOILER UI (unchanged)
    # -------------------------------------------------------------------
    def set_boiler_style(self, style_name: str):
        self._boiler_style = style_name

    def set_live_price(self, price: float, ts: float):
        self._prev_price = self._last_price
        try:
            self._last_price = float(price) if price is not None else None
        except Exception:
            self._last_price = None
        self._last_ts = ts

    def set_conversion_prices(self, from_price: float, to_price: float):
        self._conv_from_price = from_price
        self._conv_to_price = to_price

    def set_snapshot(self, live, runtime):
        self._live = live
        self._runtime = runtime
        self.set_live_price(live.get("price"), live.get("price_ts"))
        self.render_boiler()

    def render_boiler(self):
        """
        Rendering logic unchanged; compatible with Commander Edition stream.
        """
        if self._draft:
            self.boiler_label.setText("Unsaved draft — Save Changes to apply this rule.\nThe agent continues using its last saved configuration.")
            return
        t = self.trigger_combo.currentText()
        pair = self.pair_edit.text().strip()
        if t == "asset_conversion":
            source = self.from_asset_edit.text().strip().upper() or "Source"
            target = self.to_asset_edit.text().strip().upper() or "Target"
            pair = f"{source}/{target}"
        now = time.time()
        price = self._last_price
        ts = self._last_ts

        age = None
        if ts:
            age = max(0, now - ts)

        if price is None:
            price_str = "Price: —"
        else:
            price_str = f"Price: {price:.8g}"

        age_str = "Updated: —"
        if age is not None:
            age_str = "Updated: just now" if age < 1 else f"Updated: {int(age)}s ago"
            if age > 15:
                age_str += " · STALE"

        conv_lines = []
        if t in ("price_above", "price_below"):
            target = self._safe_float(self.threshold_edit.text(), None)
            if target is not None:
                quote = pair.split("/", 1)[1] if "/" in pair else "quote units"
                symbol = "≥" if t == "price_above" else "≤"
                conv_lines.append(f"Alert target: {symbol} {target:.8g} {quote}")
        conv_lines.append(self._live.get("status", "Paused" if not self.active_chk.isChecked() else "Waiting for feed"))
        conv_lines.append(f"Hits: {self._runtime.get('hits', 0)} · delivery: {self._runtime.get('delivery', '—')}")
        if self._live.get("derived"):
            conv_lines.append("Derived ratio from Phemex USDT spot prices")
        if t.startswith(("price_change", "price_delta")):
            conv_lines.append(f"Armed baseline: {self._runtime.get('baseline', 'waiting')}")
        if t == "wallet_change":
            if "confirmed_sats" in self._live:
                conv_lines.append(f"Confirmed: {self._live['confirmed_sats'] / 1e8:.8f} BTC")
                conv_lines.append(f"Pending net: {self._live['pending_sats'] / 1e8:+.8f} BTC")
                conv_lines.append(f"Confirmed transactions: {self._live['confirmed_tx_count']}")
                if "value_usdt" in self._live:
                    conv_lines.append(f"Value: {self._live['value_usdt']:,.2f} USDT")
            else:
                conv_lines.append("Awaiting Bitcoin address statistics")
        if "conversion_value" in self._live:
            conv_lines.append(f"Conversion: {self._live['conversion_value']:.8g} {self.to_asset_edit.text()}")
        if t == "asset_conversion" and "conversion_value" not in self._live:
            from_asset = self.from_asset_edit.text().strip() or "BTC"
            to_asset = self.to_asset_edit.text().strip() or "ETH"
            from_amount = self._safe_float(self.from_amount_edit.text(), 0.0)
            threshold = self._safe_float(self.threshold_edit.text(), 0.0)
            p_from = self._conv_from_price
            p_to = self._conv_to_price

            if p_from is not None and p_to is not None and p_to > 0:
                value = from_amount * p_from / p_to
                diff = threshold - value if threshold else 0.0
                pct = (value / threshold * 100.0) if threshold else 0.0

                conv_lines.append(f"{from_asset}: {p_from:,.4f} USDT")
                conv_lines.append(f"{to_asset}: {p_to:,.4f} USDT")
                conv_lines.append(f"Value: {value:,.4f} {to_asset}")
                if threshold:
                    conv_lines.append(f"Threshold: {threshold:,.4f}")
                    conv_lines.append(f"Convergence: {pct:,.1f}%")
                    conv_lines.append(f"Δ to threshold: {diff:,.4f}")
            else:
                conv_lines.append("Conversion feed: awaiting prices…")

        style = self._boiler_style
        if style == "Fusion Reactor":
            txt = self._render_reactor_style(pair, price_str, age_str, conv_lines)
        elif style == "Arcane Oracle":
            txt = self._render_oracle_style(pair, price_str, age_str, conv_lines)
        else:
            txt = self._render_cockpit_style(pair, price_str, age_str, conv_lines)

        self.boiler_label.setText(txt)

    # cockpit, reactor, oracle render methods unchanged
    def _render_cockpit_style(self, pair, price_str, age_str, conv_lines):
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f" LIVE: {pair or '—'}",
            f" {price_str}",
            f" {age_str}",
        ]
        if conv_lines:
            lines.append("")
            lines.extend(" " + ln for ln in conv_lines)
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def _render_reactor_style(self, pair, price_str, age_str, conv_lines):
        lines = [
            "╔═════════════════════════════╗",
            f"║ ⚡ {pair or '—'} REACTOR STATUS".ljust(29) + "║",
            f"║ {price_str.ljust(27)}║",
            f"║ {age_str.ljust(27)}║",
        ]
        if conv_lines:
            lines.append("║ --------------------------- ║")
            for ln in conv_lines:
                lines.append(f"║ {ln.ljust(27)}║")
        lines.append("╚═════════════════════════════╝")
        return "\n".join(lines)

    def _render_oracle_style(self, pair, price_str, age_str, conv_lines):
        title = f"⟢⟣ Arcane Oracle Feed — {pair or '—'} ⟢⟣"
        lines = [
            title,
            f"   {price_str}",
            f"   {age_str}",
        ]
        if conv_lines:
            lines.append("")
            lines.extend("   " + ln for ln in conv_lines)
        return "\n".join(lines)
