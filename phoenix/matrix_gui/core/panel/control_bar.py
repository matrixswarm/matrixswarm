from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QToolButton, QToolBar
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
import os


class PanelButton:
    def __init__(self, icon, text, handler):
        self.icon = icon
        self.text = text
        self.handler = handler


class ControlBar(QWidget):
    def __init__(self, session_window):
        super().__init__(session_window)
        try:
            self.session_window = session_window

            # === Layout ===
            self.layout = QVBoxLayout(self)
            self.layout.setContentsMargins(4, 2, 4, 2)
            self.layout.setSpacing(4)

            # --- Global font & icon setup ---
            self.icon_size = QSize(32, 32)
            self.setFont(QFont("Segoe UI Emoji", 9))

            # --- Row 1: Default buttons ---
            self.top_row = QHBoxLayout()
            self.top_row.setSpacing(8)
            self.layout.addLayout(self.top_row)

            # --- Row 2: Context buttons (hidden by default) ---
            self.secondary_row = QHBoxLayout()
            self.secondary_row.setSpacing(6)
            self.secondary_row.setContentsMargins(0, 0, 0, 0)
            self.secondary_row.setAlignment(Qt.AlignmentFlag.AlignLeft)  # ← add this
            self.layout.addLayout(self.secondary_row)
            self._secondary_visible = False

            self.default_buttons = []
            self._build_default_buttons()

            # Mount into QToolBar proxy
            session_window.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._as_toolbar_proxy())

        except Exception as e:
            emit_gui_exception_log("control_bar.__init__", e)

    # -----------------------------------
    # Default + contextual button helpers
    # -----------------------------------
    def _make_button(self, icon, text, handler):
        try:
            btn = QToolButton()
            btn.setFont(self.font())
            btn.setIconSize(getattr(self, "icon_size", QSize(28, 28)))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

            if icon and (icon.endswith(".png") or icon.endswith(".svg")) and os.path.exists(icon):
                btn.setIcon(QIcon(icon))
            elif icon:
                btn.setText(f"{icon} {text}")
            elif text:
                btn.setText(text)

            if handler:
                btn.clicked.connect(handler)

            return btn
        except Exception as e:
            emit_gui_exception_log("control_bar._make_button", e)

    def _make_toggle_button(self, icon, text, check_fn, toggle_fn):
        try:
            btn = QToolButton()
            btn.setFont(self.font())
            btn.setIconSize(self.icon_size)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setCheckable(True)
            btn.setChecked(check_fn())
            btn.setText(f"{icon} {text}")
            btn.toggled.connect(toggle_fn)
            return btn
        except Exception as e:
            emit_gui_exception_log("control_bar._make_toggle_button", e)

    # -----------------------------------
    # Public interface
    # -----------------------------------
    def clear_buttons(self):
        while self.top_row.count():
            item = self.top_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def clear_secondary_buttons(self):
        """
        Clears all non-prefix buttons from the secondary rack.
        Keeps any button explicitly tagged with _is_prefix=True.
        """
        keepers = []
        for i in range(self.secondary_row.count()):
            item = self.secondary_row.itemAt(i)
            w = item.widget()
            if w and getattr(w, "_is_prefix", False):
                keepers.append(w)

        # wipe everything
        while self.secondary_row.count():
            item = self.secondary_row.takeAt(0)
            w = item.widget()
            if w and not getattr(w, "_is_prefix", False):
                w.deleteLater()

        # reinsert kept prefix buttons
        for k in keepers:
            self.secondary_row.addWidget(k)

    def add_secondary_buttons(self, panel_buttons):
        """
        Accepts either PanelButton definitions or fully built QToolButton widgets.
        """
        for pb in panel_buttons:
            # Case 1: already a button widget
            if isinstance(pb, QToolButton):
                self.secondary_row.addWidget(pb)
                continue

            # Case 2: a PanelButton-like data holder
            icon = getattr(pb, "icon", "")
            text = getattr(pb, "text", "")
            handler = getattr(pb, "handler", None)
            btn = self._make_button(icon, text, handler)
            self.secondary_row.addWidget(btn)

        self.show_secondary_row()

    def hide_secondary_row(self):
        self._secondary_visible = False
        for i in range(self.secondary_row.count()):
            item = self.secondary_row.itemAt(i)
            if item and item.widget():
                item.widget().hide()
        self.secondary_row.setSpacing(0)

    def show_secondary_row(self):
        self._secondary_visible = True
        for i in range(self.secondary_row.count()):
            item = self.secondary_row.itemAt(i)
            if item and item.widget():
                item.widget().show()
        self.secondary_row.setSpacing(6)

    def reset_to_default(self):
        self.clear_buttons()
        for btn in self.default_buttons:
            self.top_row.addWidget(btn)
        self.clear_secondary_buttons()

    def _as_toolbar_proxy(self):
        proxy = QToolBar("ControlBarProxy")
        proxy.addWidget(self)
        return proxy

    # -----------------------------------
    # Build default row
    # -----------------------------------
    def _build_default_buttons(self):
        try:
            self.default_buttons = [
                self._make_button("", "☠️ Delete", self.session_window._launch_delete_agent),
                self._make_button("", "♻️ Replace Source", self.session_window._launch_replace_agent_source),
                self._make_button("", "🔄 Restart", self.session_window._launch_restart_agent),
                self._make_button("", "🔥 Hotswap", self.session_window._launch_hotswap_agent_modal),
                self._make_button("", "🧬 Inject", self.session_window._launch_inject_agent_modal),
                self._make_button("", "🌀 Matrix Reloaded", self.session_window._launch_matrix_reboot),
                self._make_button("", "🔀 Multiplexer", self.session_window._launch_multiplexer),

                self._make_toggle_button("", "🧵 Threads",
                    lambda: self.session_window.detail_panel.inspector_group.isVisible(),
                    self.session_window.toggle_threads_panel),
                self._make_toggle_button("", "⚙️ Config",
                    lambda: self.session_window.detail_panel.config_group.isVisible(),
                    self.session_window.toggle_config_panel),
                self._make_toggle_button("", "⏸️ Logs",
                    lambda: self.session_window.log_paused,
                    self.session_window._toggle_log_pause)
            ]
            for b in self.default_buttons:
                self.top_row.addWidget(b)
        except Exception as e:
            emit_gui_exception_log("control_bar._build_default_buttons", e)

    def add_prefix_button(self, icon="🏠", text="Main", handler=None):
        if not handler:
            return
        if hasattr(self, "_prefix_btn") and self._prefix_btn:
            self.secondary_row.removeWidget(self._prefix_btn)
            self._prefix_btn.deleteLater()
        self._prefix_btn = self._make_button(icon, text, handler)
        self._prefix_btn._is_prefix = True
        self.secondary_row.insertWidget(0, self._prefix_btn)