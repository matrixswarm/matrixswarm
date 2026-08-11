# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
import importlib
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor, QPen, QPainter, QKeyEvent, QFont
from .cls_lib.agent.config_editors.base_editor import BaseEditor
from .cls_lib.color.color_manager import ColorManager
from .cls_lib.agent.agent_node import AgentNode

class AgentItem(QGraphicsRectItem):
    WIDTH, HEIGHT = 160, 60

    def __init__(self, node: AgentNode):
        super().__init__(0, 0, self.WIDTH, self.HEIGHT)

        # -----------------------------
        # MODEL (AgentNode)
        # -----------------------------
        self.node = node                  # ← REAL agent model
        self.meta = node.meta             # ← static meta.json

        # visual state
        self.color = QColor("#888")
        self.depth = 0

        # -----------------------------
        # MATRIX special rules
        # -----------------------------
        if node.name == "matrix":
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            self.color = QColor("#3a78ff")
            self.setToolTip("👑 MATRIX – Root of the Swarm")

        # -----------------------------
        # Base visuals
        # -----------------------------
        self.setBrush(QColor("#1e1e1e"))
        self.setPen(QPen(QColor("#888")))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)


        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor("#3a78ff"))
        shadow.setOffset(0, 0)
        self.setGraphicsEffect(shadow)
    # ---------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events."""
        if event.key() == Qt.Key.Key_Delete:  # Check if the 'Delete' key was pressed
            self.request_delete()  # Call the delete method when Delete key is pressed
            event.accept()  # Mark the event as handled
        else:
            event.ignore()  # Pass the event to the parent handler if not Delete
    # ---------------------------------------------------------
    def request_delete(self):
        """Ask the controller to delete this agent."""
        scene = self.scene()
        ws = getattr(scene, "workspace", None)
        if ws and hasattr(ws, "controller"):
            ws.controller.delete_node(self)
            ws.save()
        else:
            # Fallback if no controller is wired (shouldn't happen)
            scene.removeItem(self)

    # ---------------------------------------------------------
    def mouseDoubleClickEvent(self, event):
        if self.node.get_name().lower() == "matrix":
            return

        name = self.node.get_name().lower()
        try:
            print(f"config editor loading .... matrix_gui.swarm_workspace.cls_lib.agent.config_editors.{name}")
            mod = importlib.import_module(f"matrix_gui.swarm_workspace.cls_lib.agent.config_editors.{name}")
            # Convert snake_case to CamelCase for class lookup
            class_name = "".join(part.capitalize() for part in name.split("_"))
            Editor = getattr(mod, class_name)
        except (ImportError, AttributeError):
            Editor = BaseEditor

        dlg = Editor(self.node)
        if dlg.exec():
            self.scene().workspace.save()  # save workspace immediately

    # ---------------------------------------------------------
    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)

        # Load this agent into the inspector
        ws = getattr(self.scene(), "workspace", None)
        if ws:
            class_list = []   # not needed; inspector parses constraints from node
            ws.inspector.load(self.node, class_list)


    # ---------------------------------------------------------
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_focused = self.hasFocus() or self.isSelected()
        border_color = QColor("#3a78ff") if is_focused else QColor("#888")
        fill_color = QColor("#1e1e1e")

        pen = QPen(border_color)
        pen.setWidth(3 if is_focused else 2)
        painter.setPen(pen)
        painter.setBrush(fill_color)
        painter.drawRoundedRect(self.rect(), 8, 8)

        # text
        name = self.node.universal_id
        emoji = (
                self.node.config.get("ui", {}).get("agent_tree", {}).get("emoji", "")
                or self.meta.get("ui", {}).get("agent_tree", {}).get("emoji", "")
        )

        # --- Fix corrupted emoji encoding ---
        if isinstance(emoji, str) and "ð" in emoji:
            try:
                emoji = emoji.encode("latin1").decode("utf-8")
            except Exception:
                pass

        label = f"{emoji} {name}" if emoji else name

        emoji_font = QFont("Segoe UI Emoji", 10)
        emoji_font.setBold(True)
        painter.setFont(emoji_font)
        painter.setPen(QColor("#fff"))
        painter.drawText(
            self.rect().adjusted(6, 6, -6, -6),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            label
        )

    # ---------------------------------------------------------
    def set_hierarchy_info(self, depth: int):
        self.depth = depth
        self.color = ColorManager.color_for_depth(depth)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            pos = self.pos()
            self.node.set_position(pos.x(), pos.y())
        return super().itemChange(change, value)

    def update_status_color(self):
        if self.node.all_constraints_met():
            self.setPen(QPen(QColor("#369CFF"), 3))
        else:
            self.setPen(QPen(QColor("#555"), 2))
