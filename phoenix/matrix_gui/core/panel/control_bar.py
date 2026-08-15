from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class PanelButton:
    def __init__(self, icon, text, handler):
        self.icon = icon
        self.text = text
        self.handler = handler


class ControlBar(QWidget):
    """Phoenix's session-scoped command deck.

    The application toolbar above this widget owns deployment-wide work. This
    deck owns the live session: its selected target, agent operations, route,
    and view controls. Contextual panel actions live on the smaller rail below
    it and never leak back into the cockpit view.
    """

    def __init__(self, session_window):
        super().__init__(session_window)
        try:
            self.session_window = session_window
            self.icon_size = QSize(16, 16)
            self._selected_uid = None
            self._selected_label = "Select an agent"
            self.setObjectName("PhoenixControlDeck")
            self.setFont(QFont("Segoe UI", 9))

            self.setStyleSheet(
                """
                QWidget#PhoenixControlDeck {
                    background: #0d0f13;
                    border: 1px solid #20242c;
                    border-radius: 7px;
                }
                QLabel#ControlTargetBadge {
                    color: #9cf7e2;
                    background: #102927;
                    border: 1px solid #1abda8;
                    border-radius: 5px;
                    font-family: "Segoe UI Semibold";
                    padding: 6px 10px;
                }
                QLabel#ControlContextLabel {
                    color: #9099aa;
                    font-size: 8pt;
                    font-family: "Segoe UI Semibold";
                    padding: 3px 7px;
                }
                QToolButton#ControlDeckButton {
                    color: #e3e7ee;
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 5px;
                    padding: 6px 8px;
                }
                QToolButton#ControlDeckButton:hover {
                    color: #b8fff1;
                    background: #18242b;
                    border-color: #286c6d;
                }
                QToolButton#ControlDeckButton:pressed {
                    background: #21353c;
                }
                QToolButton#ControlDeckButton:checked {
                    color: #9cf7e2;
                    background: #173b3b;
                    border-color: #19cbb4;
                }
                QToolButton#ControlDeckButton:disabled {
                    color: #5d6674;
                }
                QFrame#ControlDeckDivider {
                    color: #2a303b;
                    background: #2a303b;
                    max-width: 1px;
                    margin: 5px 4px;
                }
                QMenu {
                    color: #e3e7ee;
                    background: #14171d;
                    border: 1px solid #353c49;
                    padding: 4px;
                }
                QMenu::item { padding: 7px 24px 7px 12px; }
                QMenu::item:selected { background: #253941; color: #b8fff1; }
                """
            )

            self.layout = QVBoxLayout(self)
            self.layout.setContentsMargins(5, 4, 5, 3)
            self.layout.setSpacing(2)

            self.top_row = QHBoxLayout()
            self.top_row.setContentsMargins(1, 0, 1, 0)
            self.top_row.setSpacing(2)
            self.top_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.layout.addLayout(self.top_row)

            self.secondary_row = QHBoxLayout()
            self.secondary_row.setContentsMargins(2, 0, 2, 1)
            self.secondary_row.setSpacing(2)
            self.secondary_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.layout.addLayout(self.secondary_row)

            self.context_label = QLabel("CONTEXT  /  Cockpit")
            self.context_label.setObjectName("ControlContextLabel")
            self.context_label._is_persistent = True
            self.secondary_row.addWidget(self.context_label)
            self._secondary_visible = False

            self.default_buttons = []
            self._build_default_buttons()
            self.hide_secondary_row()

            session_window.addToolBar(
                Qt.ToolBarArea.TopToolBarArea,
                self._as_toolbar_proxy(),
            )
        except Exception as e:
            emit_gui_exception_log("control_bar.__init__", e)

    # -----------------------------------
    # Button + layout helpers
    # -----------------------------------
    def _make_button(self, icon, text, handler, tooltip=None, checkable=False):
        try:
            btn = QToolButton()
            btn.setObjectName("ControlDeckButton")
            btn.setFont(self.font())
            btn.setIconSize(self.icon_size)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setAutoRaise(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCheckable(checkable)
            btn.setText(f"{icon}  {text}".strip() if icon else text)
            btn.setToolTip(tooltip or text)
            btn.setStatusTip(tooltip or text)
            btn.setAccessibleName(text)

            if handler:
                # Do not pass QToolButton's checked bool into optional uid args.
                btn.clicked.connect(lambda _checked=False: handler())
            return btn
        except Exception as e:
            emit_gui_exception_log("control_bar._make_button", e)

    def _make_toggle_button(self, icon, text, check_fn, toggle_fn, tooltip):
        btn = self._make_button(icon, text, None, tooltip, checkable=True)
        if not btn:
            return None
        try:
            btn.setChecked(bool(check_fn()))
            btn.toggled.connect(lambda _checked: toggle_fn())
        except Exception as e:
            emit_gui_exception_log("control_bar._make_toggle_button", e)
        return btn

    def _add_divider(self):
        divider = QFrame()
        divider.setObjectName("ControlDeckDivider")
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setFixedHeight(24)
        self.top_row.addWidget(divider)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _run_for_selected_agent(self, handler):
        """Prefer the live tree target, while preserving modal fallback."""
        if self._selected_uid:
            handler(self._selected_uid)
        else:
            handler()

    # -----------------------------------
    # Public interface
    # -----------------------------------
    def clear_buttons(self):
        self._clear_layout(self.top_row)

    def clear_secondary_buttons(self):
        """Clear contextual actions while retaining the breadcrumb label."""
        keepers = []
        while self.secondary_row.count():
            item = self.secondary_row.takeAt(0)
            widget = item.widget()
            if widget and getattr(widget, "_is_persistent", False):
                keepers.append(widget)
            elif widget:
                widget.deleteLater()

        for keeper in keepers:
            self.secondary_row.addWidget(keeper)

    def remove_prefix_button(self):
        if getattr(self, "_prefix_btn", None):
            self.secondary_row.removeWidget(self._prefix_btn)
            self._prefix_btn.deleteLater()
            self._prefix_btn = None

    def set_context(self, text="Cockpit"):
        self.context_label.setText(f"CONTEXT  /  {text}")
        self.context_label.setToolTip(text)

    def set_selected_agent(self, node):
        """Reflect the latest tree selection without owning tree state."""
        try:
            node = node or {}
            uid = node.get("universal_id") or node.get("uid") or node.get("id")
            label = node.get("name") or node.get("agent_name") or uid or "Select an agent"
            status = node.get("agent_status") or node.get("status")
            if isinstance(status, dict):
                status = status.get("state") or status.get("status")

            self._selected_uid = uid
            self._selected_label = str(label)
            badge_text = f"TARGET  ·  {self._selected_label}"
            if status:
                badge_text += f"  ·  {str(status).upper()}"
            self.target_badge.setText(badge_text)
            self.target_badge.setToolTip(
                f"Selected agent: {self._selected_label}"
                + (f"\nUniversal ID: {uid}" if uid else "")
            )
        except Exception as e:
            emit_gui_exception_log("control_bar.set_selected_agent", e)

    def refresh_toggle_states(self):
        """Synchronize view toggles after a panel changes outside the deck."""
        try:
            for button, checked in (
                (getattr(self, "threads_btn", None), self.session_window.detail_panel.inspector_group.isVisible()),
                (getattr(self, "config_btn", None), self.session_window.detail_panel.config_group.isVisible()),
                (getattr(self, "logs_btn", None), self.session_window.log_paused),
            ):
                if button:
                    button.blockSignals(True)
                    button.setChecked(bool(checked))
                    button.blockSignals(False)
        except Exception as e:
            emit_gui_exception_log("control_bar.refresh_toggle_states", e)

    def add_secondary_buttons(self, panel_buttons):
        """Add contextual actions using the same quiet deck styling."""
        for pb in panel_buttons:
            if isinstance(pb, QToolButton):
                pb.setObjectName("ControlDeckButton")
                pb.setAutoRaise(True)
                self.secondary_row.addWidget(pb)
                continue

            text = getattr(pb, "text", "")
            handler = getattr(pb, "handler", None)
            # Legacy custom-panel emoji stay out of the shared control deck.
            btn = self._make_button("", text, handler)
            self.secondary_row.addWidget(btn)
        self.show_secondary_row()

    def hide_secondary_row(self):
        self._secondary_visible = False
        for index in range(self.secondary_row.count()):
            item = self.secondary_row.itemAt(index)
            if item and item.widget():
                item.widget().hide()
        self.secondary_row.setSpacing(0)

    def show_secondary_row(self):
        self._secondary_visible = True
        for index in range(self.secondary_row.count()):
            item = self.secondary_row.itemAt(index)
            if item and item.widget():
                item.widget().show()
        self.secondary_row.setSpacing(2)

    def reset_to_default(self):
        self.clear_buttons()
        self._build_default_buttons()
        self.remove_prefix_button()
        self.clear_secondary_buttons()
        self.set_context("Cockpit")
        self.hide_secondary_row()

    def _as_toolbar_proxy(self):
        proxy = QToolBar("Phoenix Session Controls")
        proxy.setObjectName("PhoenixSessionControls")
        proxy.setMovable(False)
        proxy.setFloatable(False)
        proxy.addWidget(self)
        return proxy

    # -----------------------------------
    # Build primary command deck
    # -----------------------------------
    def _build_default_buttons(self):
        try:
            self.target_badge = QLabel("TARGET  ·  Select an agent")
            self.target_badge.setObjectName("ControlTargetBadge")
            self.target_badge.setMinimumWidth(235)
            self.target_badge.setMaximumWidth(320)
            self.target_badge.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.top_row.addWidget(self.target_badge)
            self._add_divider()

            self.restart_btn = self._make_button(
                "↻", "Restart",
                lambda: self._run_for_selected_agent(self.session_window._launch_restart_agent),
                "Restart the selected agent, or choose one in the dialog.",
            )
            self.replace_btn = self._make_button(
                "⇄", "Replace Source", self.session_window._launch_replace_agent_source,
                "Replace an agent source package.",
            )
            self.hotswap_btn = self._make_button(
                "⇋", "Hotswap",
                lambda: self._run_for_selected_agent(self.session_window._launch_hotswap_agent_modal),
                "Swap the selected agent without leaving the session.",
            )
            self.inject_btn = self._make_button(
                "↳", "Inject",
                lambda: self._run_for_selected_agent(self.session_window._launch_inject_agent_modal),
                "Inject a directive into the selected agent.",
            )
            self.default_buttons = [self.restart_btn, self.replace_btn, self.hotswap_btn, self.inject_btn]
            for button in self.default_buttons:
                self.top_row.addWidget(button)

            self._add_divider()
            self.routes_btn = self._make_button(
                "⇌", "Routes", self.session_window._launch_multiplexer,
                "Inspect or change the live ingress and egress routes.",
            )
            self.reload_btn = self._make_button(
                "↺", "Reload…", self.session_window._launch_matrix_reboot,
                "Open the swarm redeploy dialog.",
            )
            self.top_row.addWidget(self.routes_btn)
            self.top_row.addWidget(self.reload_btn)

            self._add_divider()
            self.threads_btn = self._make_toggle_button(
                "≡", "Inspector",
                lambda: self.session_window.detail_panel.inspector_group.isVisible(),
                self.session_window.toggle_threads_panel,
                "Show or hide the selected agent inspector.",
            )
            self.config_btn = self._make_toggle_button(
                "⚙", "Config",
                lambda: self.session_window.detail_panel.config_group.isVisible(),
                self.session_window.toggle_config_panel,
                "Show or hide agent configuration details.",
            )
            self.logs_btn = self._make_toggle_button(
                "Ⅱ", "Pause Logs",
                lambda: self.session_window.log_paused,
                self.session_window._toggle_log_pause,
                "Pause or resume the live log stream.",
            )
            self.top_row.addWidget(self.threads_btn)
            self.top_row.addWidget(self.config_btn)
            self.top_row.addWidget(self.logs_btn)

            self.top_row.addStretch(1)
            self.more_btn = self._make_button("⋯", "More", None, "Additional session actions.")
            menu = QMenu(self.more_btn)
            delete_action = menu.addAction("Delete selected agent…")
            delete_action.setToolTip("Permanently delete the selected agent.")
            delete_action.triggered.connect(
                lambda _checked=False: self._run_for_selected_agent(self.session_window._launch_delete_agent)
            )
            self.more_btn.setMenu(menu)
            self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.top_row.addWidget(self.more_btn)
        except Exception as e:
            emit_gui_exception_log("control_bar._build_default_buttons", e)

    def add_prefix_button(self, icon="‹", text="Cockpit", handler=None):
        if not handler:
            return
        self.remove_prefix_button()
        self._prefix_btn = self._make_button(icon, text, handler, "Return to the cockpit.")
        self._prefix_btn._is_persistent = True
        self.secondary_row.insertWidget(0, self._prefix_btn)