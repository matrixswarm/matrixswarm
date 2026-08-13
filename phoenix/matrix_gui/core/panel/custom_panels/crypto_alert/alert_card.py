# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals

import time
from typing import Dict
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox
)
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QFrame

class AlertCard(QWidget):
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

        self._build_ui()

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
        hdr.addWidget(self.header_label)
        hdr.addStretch()

        self.delete_btn = QPushButton("✕")
        self.delete_btn.setObjectName("deleteBtn")
        self.delete_btn.setFixedSize(26, 26)
        hdr.addWidget(self.delete_btn)

        root.addLayout(hdr)

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
        ])
        trig_row.addWidget(self.trigger_combo)
        wrap = QWidget()
        wrap.setLayout(trig_row)
        root.addWidget(wrap)

        # -------------------------------------------------------
        # Main threshold
        thresh_row = QHBoxLayout()
        thresh_row.addWidget(QLabel("Threshold:"))
        self.threshold_edit = QLineEdit("0")
        thresh_row.addWidget(self.threshold_edit)
        wrap = QWidget()
        wrap.setLayout(thresh_row)
        root.addWidget(wrap)

        # -------------------------------------------------------
        # Percent change
        pct_row = QHBoxLayout()
        pct_row.addWidget(QLabel("Percent Change:"))
        self.pct_edit = QLineEdit("")
        pct_row.addWidget(self.pct_edit)
        self.pct_wrap = QWidget()
        self.pct_wrap.setLayout(pct_row)
        root.addWidget(self.pct_wrap)

        # -------------------------------------------------------
        # Absolute delta
        delta_row = QHBoxLayout()
        delta_row.addWidget(QLabel("Delta ($):"))
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
        r.addWidget(QLabel("Amount:"))
        self.from_amount_edit = QLineEdit("0.1")
        r.addWidget(self.from_amount_edit)
        conv_layout.addLayout(r)

        root.addWidget(self.conv_wrap)

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
        tlim_row.addWidget(QLabel("Trigger Limit:"))
        self.trigger_limit_edit = QLineEdit("9999999")
        tlim_row.addWidget(self.trigger_limit_edit)
        wrap = QWidget()
        wrap.setLayout(tlim_row)
        root.addWidget(wrap)

        # -------------------------------------------------------
        # Boiler display (unchanged)
        self.boiler_frame = QWidget()
        b = QVBoxLayout(self.boiler_frame)
        b.setContentsMargins(6, 6, 6, 6)
        b.setSpacing(2)

        self.boiler_label = QLabel("")
        self.boiler_label.setObjectName("boilerLabel")
        self.boiler_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.boiler_label.setWordWrap(True)
        b.addWidget(self.boiler_label)
        root.addWidget(self.boiler_frame)

        # Hide/show dynamic fields
        self.trigger_combo.currentTextChanged.connect(self._update_field_visibility)
        self._update_field_visibility()

        # clicking outside inputs toggles Active
        self.installEventFilter(self)

        # Force stable minimum size so cards never collapse or flicker
        self.setMinimumHeight(360)
        self.setMinimumWidth(350)
        self.setAutoFillBackground(True)



    # -------------------------------------------------------------------
    # FIELD VISIBILITY
    # -------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            # Only toggle active state if click is on empty card background
            child = self.childAt(event.pos())
            if child is None:
                self.active_chk.toggle()
                return True
        return False

    def _update_field_visibility(self):
        t = self.trigger_combo.currentText()
        self.pct_wrap.setVisible("price_change" in t)
        self.delta_wrap.setVisible("price_delta" in t)
        self.conv_wrap.setVisible("asset_conversion" in t)

        pair = self.pair_edit.text().strip()
        self.header_label.setText(f"{pair or 'Pair'} · {t}")


    # -------------------------------------------------------------------
    # DICT <-> CARD
    # -------------------------------------------------------------------

    def to_dict(self) -> Dict:
        """Match EXACT structure backend Commander Edition expects."""
        t = self.trigger_combo.currentText()

        d = {
            "pair": self.pair_edit.text().strip(),
            "trigger_type": t,
            "threshold": self._safe_float(self.threshold_edit.text()),
            "active": self.active_chk.isChecked(),
            "alert_enabled": self.alert_enabled_chk.isChecked(),
            "stream_enabled": self.stream_enabled_chk.isChecked(),
            "trigger_limit": int(self._safe_float(self.trigger_limit_edit.text(), 9999999)),
        }

        # percent change
        if "price_change" in t:
            d["change_percent"] = self._safe_float(self.pct_edit.text())

        # absolute delta
        if "price_delta" in t:
            d["change_absolute"] = self._safe_float(self.delta_edit.text())

        # conversion
        if t == "asset_conversion":
            d["from_asset"] = self.from_asset_edit.text().strip()
            d["to_asset"] = self.to_asset_edit.text().strip()
            d["from_amount"] = self._safe_float(self.from_amount_edit.text())

        return d

    def from_dict(self, alert: Dict):
        """Populate card fields from backend config."""
        self.pair_edit.setText(alert.get("pair", "BTC/USDT"))

        ttype = alert.get("trigger_type", "price_above")
        self.trigger_combo.setCurrentText(ttype)

        self.threshold_edit.setText(str(alert.get("threshold", 0)))
        self.active_chk.setChecked(alert.get("active", True))
        self.alert_enabled_chk.setChecked(alert.get("alert_enabled", True))
        self.stream_enabled_chk.setChecked(alert.get("stream_enabled", True))

        self.trigger_limit_edit.setText(str(alert.get("trigger_limit", 9999999)))

        self.pct_edit.setText(str(alert.get("change_percent", "")))
        self.delta_edit.setText(str(alert.get("change_absolute", "")))
        self.from_asset_edit.setText(alert.get("from_asset", "BTC"))
        self.to_asset_edit.setText(alert.get("to_asset", "ETH"))
        self.from_amount_edit.setText(str(alert.get("from_amount", "")))

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

    def render_boiler(self):
        """
        Rendering logic unchanged; compatible with Commander Edition stream.
        """
        t = self.trigger_combo.currentText()
        pair = self.pair_edit.text().strip()
        now = time.time()
        price = self._last_price
        ts = self._last_ts

        age = None
        if ts:
            age = max(0, now - ts)

        if price is None:
            price_str = "Price: —"
        else:
            price_str = f"Price: {price:,.4f}"

        age_str = "Updated: —"
        if age is not None:
            age_str = "Updated: just now" if age < 1 else f"Updated: {int(age)}s ago"

        conv_lines = []
        if t == "asset_conversion":
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
