# Authored by Daniel F MacDonald and ChatGPT aka The Generals

import uuid, time, hashlib, json, datetime
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QHeaderView, QTreeWidget, QTreeWidgetItem, QLabel
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from PyQt5.QtCore import Qt, QTimer


class PhoenixAgentTree(QWidget):
    def __init__(self, session_id, vault_data=None, bus=None, parent=None):
        super().__init__(parent)
        try:
            self.vault_data = vault_data or {}
            self.bus = bus

            self.bound_session_id = session_id
            self.parent = parent  # optional
            self.active_log_token = None  # can be used locally or emitted via signal

            # === Layout
            layout = QVBoxLayout()
            self.setLayout(layout)

            self.status_label = QLabel("Agent Tree: ⏳ Loading...")
            layout.addWidget(self.status_label)

            self._last_payload_hash = None
            self._last_tree_update_ts = None

            self.flip_tripping_threshold = 1

            # === Agent tree widget
            self.tree = QTreeWidget()
            self.tree.setColumnCount(1)
            self.tree.setHeaderHidden(True)
            self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.tree.setSelectionMode(QTreeWidget.SingleSelection)
            self.tree.itemClicked.connect(self._on_tree_item_clicked)
            layout.addWidget(self.tree)

            # === Agent detail panel

            layout.setStretch(0, 0)  # status label
            layout.setStretch(1, 3)  # tree

            self.tree.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

            self.tree.setMinimumHeight(180)

            # === Bind to session bus updates
            if self.bus:
                self.bus.on(
                    f"inbound.verified.agent_tree_master.update.{self.bound_session_id}",
                    self._handle_tree_update
                )
                print(f"[AGENT_TREE] Subscribed to bus: inbound.verified.agent_tree_master.update.{self.bound_session_id}")

        except Exception as e:
            emit_gui_exception_log("PhoenixAgentTree.__init__", e)

    def _on_tree_item_clicked(self, item):
        try:
            node = item.node_data
            uid = node.get("universal_id")
            if not uid or not self.bus:
                return

            token = str(uuid.uuid4())
            self.active_log_token = token
            #self.detail_panel.set_agent_data(node)

            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "hive.log",
                    "payload": {
                        "target_agent": uid,
                        "session_id": self.bound_session_id,
                        "token": token,
                        "follow": True,
                        "return_handler": "agent_log_view.update"
                    }
                }
            })

            self.bus.emit("gui.agent.selected", session_id=self.bound_session_id, node=node)
            self.bus.emit("gui.log.token.updated", session_id=self.bound_session_id, token=token, agent_title=node.get("name", uid))
            self.bus.emit("outbound.message", session_id=self.bound_session_id, channel="outgoing.command", packet=pk)

            print(f"[AGENT_TREE] 🔍 Sent fetch_logs for agent {uid} with token={token}")

        except Exception as e:
            emit_gui_exception_log("PhoenixAgentTree._on_tree_item_clicked", e)

    def _handle_tree_update(self, payload, **_):
        try:
            content = payload.get("content", {})
            new_hash = self._compute_payload_hash(content)

            if new_hash == self._last_payload_hash:
                self._last_tree_update_ts = time.time()
                self._update_status_label()
                return

            self._last_payload_hash = new_hash
            self._last_tree_update_ts = time.time()
            self._render_tree(content)
            self._update_status_label()

            QTimer.singleShot(0, self.tree.expandAll)

        except Exception as e:
            emit_gui_exception_log("PhoenixAgentTree._handle_tree_update", e)

    def _update_status_label(self):
        try:
            ts = self._last_tree_update_ts or time.time()
            time_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            self.status_label.setText(f"Agent Tree: ✅ Updated at {time_str}")
        except Exception as e:
            emit_gui_exception_log("PhoenixAgentTree._update_status_label", e)

    def _render_tree(self, tree_data):
        try:
            self.tree.clear()

            def build(parent, node):
                if not isinstance(node, dict):
                    return

                # Extract base name and children
                base = str(node.get("name") or node.get("universal_id") or "Unnamed")
                children = node.get("children", [])
                child_count = len(children)

                # Flip-trip check
                flip_count = (
                    node.get("agent_status", {})
                    .get("spawn", {})
                    .get("count", 0)
                )

                flip_marker = ""
                if flip_count > self.flip_tripping_threshold:  # threshold, tweak as you like
                    flip_marker = f"    ⚠"

                # Icon + Title
                icon = "🧬" if children else "🔹"
                title = f"{icon} {base} ({child_count}){flip_marker}" if children else f"{icon} {base}{flip_marker}"


                # Create the tree item
                item = QTreeWidgetItem([title])
                item.node_data = node

                # Tooltip if marked
                if flip_count > self.flip_tripping_threshold:
                    item.setToolTip(0, f"This agent flip-tripped {flip_count} times.")

                # Bold font if it has children
                font = item.font(0)
                if children:
                    font.setBold(True)
                item.setFont(0, font)

                # Attach to parent or root
                if parent:
                    parent.addChild(item)
                else:
                    self.tree.addTopLevelItem(item)

                # Recurse
                for child in children:
                    build(item, child)


            build(None, tree_data)

        except Exception as e:
            emit_gui_exception_log("PhoenixAgentTree._render_tree", e)

    def closeEvent(self, event):
        try:
            if self.bus:
                self.bus.off(
                    f"inbound.verified.agent_tree_master.update.{self.bound_session_id}",
                    self._handle_tree_update
                )
                print(f"[AGENT_TREE] Unsubscribed from agent_tree_master.update.{self.bound_session_id}")
            super().closeEvent(event)
        except Exception as e:
            emit_gui_exception_log("PhoenixAgentTree.closeEvent", e)


    def _build_node(self, parent_item, node):
        name, health = self._format_display(node)
        item = QTreeWidgetItem([name, health])
        item.setData(0, Qt.UserRole, node)
        parent_item.addChild(item)

        for child in node.get("children", []):
            self._build_node(item, child)

    def _format_display(self, node: dict):
        name = node.get("name", "unnamed")
        spawn = node.get("agent_status", {}).get("spawn", {})
        cnt = spawn.get("count", 0)
        symbol = f"⚡{cnt}" if cnt else ""
        return name, symbol

    def _compute_payload_hash(self, payload: dict):
        try:
            def prune(d):
                if isinstance(d, dict):
                    return {k: prune(v) for k, v in d.items() if k != "agent_status"}
                elif isinstance(d, list):
                    return [prune(i) for i in d]
                return d

            cleaned = prune(payload)
            serialized = json.dumps(cleaned, sort_keys=True)
            return hashlib.md5(serialized.encode()).hexdigest()
        except Exception as e:
            emit_gui_exception_log("PhoenixAgentTree._compute_payload_hash", e)
            return None
