# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import uuid, time
from PyQt6.QtWidgets import QVBoxLayout, QLabel, QGridLayout, QPushButton, QHBoxLayout
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from PyQt6.QtMultimedia import QSoundEffect
from PyQt6.QtCore import QUrl

from PyQt6.QtCore import QThread, QMetaObject, Qt, pyqtSlot, Q_ARG
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from collections import deque
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface

class Gameboard(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        try:
            # … keep the rest of your initialization …
            self._initialized = False
            self._resizing = False
            self._frame_queue = deque(maxlen=5)

            if not self._initialized:
                self.cowbell_sound = QSoundEffect()
                self.cowbell_sound.setSource(QUrl.fromLocalFile("matrix_gui/resources/sounds/cowbell.wav"))
                self.cowbell_sound.setLoopCount(1)  # already has 4 hits
                self.cowbell_sound.setVolume(0.9)
                self.setLayout(self._build_layout())
                self._connect_signals()
                self._initialized = True

        except Exception as e:
            emit_gui_exception_log("Gameboard.__init__", e)

    # --- Required abstract methods from PhoenixPanelInterface ---
    def _connect_signals(self):
        """Attach bus listener for NPC simulator responses."""
        try:
            if getattr(self, "_signals_connected", False):
                return
            scoped_handler = "inbound.verified.npc_simulator.gameboard.response"
            self.bus.on(scoped_handler, self._handle_gameboard_response)
            self._signals_connected = True
            print(f"[GAMEBOARD] 🎧 Connected to {scoped_handler}")
        except Exception as e:
            emit_gui_exception_log("Gameboard._connect_signals", e)

    def _disconnect_signals(self):
        """Detach bus listener and clear pending frame queue."""
        try:
            if not getattr(self, "_signals_connected", False):
                return
            scoped_handler = "inbound.verified.npc_simulator.gameboard.response"
            if hasattr(self, "bus") and self.bus:
                self.bus.off(scoped_handler, self._handle_gameboard_response)
            self._signals_connected = False
            self._frame_queue.clear()
            print(f"[GAMEBOARD] 🔕 Disconnected from {scoped_handler}")
        except Exception as e:
            emit_gui_exception_log("Gameboard._disconnect_signals", e)

    def get_panel_buttons(self):
        """Return toolbar button for the NPC simulator panel."""
        return [
            PanelButton("🎮", "NPC Panel",
                        lambda: self.session_window.show_specialty_panel(self))
        ]

    def _on_show(self):
        """Optional: redraw grid when panel becomes visible."""
        if getattr(self, "has_drawn", False):
            self._update_grid(self.last_player_pos, self.last_npc_list)


    def _build_layout(self):
        try:
            layout = QVBoxLayout()
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(10)

            # Title
            title = QLabel("🎮 NPC Simulator Panel")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("font-weight: bold; font-size: 16px;")
            layout.addWidget(title)

            # Button row
            btn_row = QHBoxLayout()
            btn_row.setSpacing(6)
            buttons = [
                ("Start", self.start_stream_clicked),
                ("Stop", self.stop_stream_clicked),
                ("Hunt", self.hunt_clicked),
                ("Scatter", self.scatter_clicked),
                ("Ping", self.ping_clicked),
                ("Shield", self.shield_clicked),
                ("Lock", self.lock_clicked),
                ("Cowbell", self.cowbell_clicked)
            ]
            for label, handler in buttons:
                btn = QPushButton(label)
                btn.clicked.connect(handler)
                btn_row.addWidget(btn)
            layout.addLayout(btn_row)

            # Grid display
            self.grid_size = 20  # same as npc agent default
            self.grid = QGridLayout()
            self.grid.setSpacing(2)
            self.cells = []
            self.has_drawn = False
            for y in range(self.grid_size):
                row = []
                for x in range(self.grid_size):
                    cell = QLabel(" ")
                    cell.setFixedSize(20, 20)
                    cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    cell.setStyleSheet("border: 1px solid #333; background: #111; color: #fff;")
                    self.grid.addWidget(cell, y, x)
                    row.append(cell)
                self.cells.append(row)


            layout.addLayout(self.grid)
            return layout
        except Exception as e:
            emit_gui_exception_log("Gameboard._build_layout", e)

    def _update_grid(self, player_pos, npc_list):
        if QThread.currentThread() != QApplication.instance().thread():
            self._pending_frame = (player_pos, npc_list)
            if not hasattr(self, "_frame_timer"):
                self._frame_timer = QTimer()
                self._frame_timer.setSingleShot(True)
                self._frame_timer.timeout.connect(self._flush_pending_frame)
            if not self._frame_timer.isActive():
                self._frame_timer.start(50)  # flush in 50ms
            return
        self._update_grid_safe(player_pos, npc_list)

    def _flush_pending_frame(self):
        if hasattr(self, "_pending_frame"):
            px, npcs = self._pending_frame
            self._update_grid_safe(px, npcs)
            del self._pending_frame


    @pyqtSlot(object, object)
    def _update_grid_safe(self, player_pos, npc_list):
        self.setUpdatesEnabled(False)
        try:
            grid_size = self.grid_size
            seen = set()

            # Clear grid
            for y in range(grid_size):
                for x in range(grid_size):
                    try:
                        if not self._is_valid_cell(x, y):
                            print(f"[GRID] 🚫 Skipping invalid NPC")
                            continue
                        self.cells[y][x].setText(" ")
                        self.cells[y][x].setStyleSheet("border: 1px solid #333; background: #111;")
                    except Exception as e:
                        print(f"[GRID] ❌ Failed to clear {x},{y} – {e}")

            # Draw player
            px, py = player_pos
            if 0 <= px < grid_size and 0 <= py < grid_size:
                self.cells[py][px].setText("@")
                self.cells[py][px].setStyleSheet("border: 1px solid #555; background: #444; color: #0f0;")

            # Draw last seen player position (if enabled)
            if (
                    getattr(self, "last_seen_player", None) is not None
                    and isinstance(self.last_seen_player, (list, tuple))
                    and self._is_valid_cell(*self.last_seen_player)
            ):
                lx, ly = self.last_seen_player
                self.cells[ly][lx].setText("X")
                self.cells[ly][lx].setStyleSheet("border: 1px solid #f00; background: #300; color: #f44;")

            # Draw NPCs
            for npc in npc_list:
                x = npc.get("x")
                y = npc.get("y")
                role = npc.get("role", "unknown")
                key = (x, y)

                if x is None or y is None:
                    print(f"[GRID] ⚠️ Skipping NPC with invalid coords: {npc}")
                    continue

                if 0 <= x < grid_size and 0 <= y < grid_size:
                    try:
                        if key in seen:
                            existing = self.cells[y][x].text()
                            if existing.isdigit():
                                self.cells[y][x].setText(str(int(existing) + 1))
                            else:
                                self.cells[y][x].setText("2")
                            continue

                        color = {
                            "scout": "#ff0",
                            "hunter": "#f00",
                            "follower": "#0cf"
                        }.get(role, "#fff")

                        if not self._is_valid_cell(x, y):
                            print(f"[GRID] 🚫 Skipping invalid NPC")
                            continue

                        self.cells[y][x].setText("o")
                        self.cells[y][x].setStyleSheet(f"border: 1px solid #444; background: #222; color: {color};")

                    except Exception as e:
                        print(f"[GRID] ❌ Failed to draw NPC at {x},{y} – {e}")
                else:
                    print(f"[GRID] 🚫 Out-of-bounds NPC: {npc}")

            self._overlap_warned = False

        except Exception as e:
            emit_gui_exception_log("Gameboard._update_grid", e)

        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def resizeEvent(self, event):
        self._resizing = True
        super().resizeEvent(event)
        self._resizing = False

    def _is_valid_cell(self, x, y):
        """Check if x and y are within grid bounds."""
        if x is None or y is None:
            return False
        return 0 <= x < self.grid_size and 0 <= y < self.grid_size


    # === Button Actions ===
    def hunt_clicked(self):
        self._send_action("hunt")

    def scatter_clicked(self):
        self._send_action("scatter")


    def ping_clicked(self):
        self._send_action("ping")

    def shield_clicked(self):
        self._send_action("shield")

    def lock_clicked(self):
        self._send_action("lock")

    def cowbell_clicked(self):
        self.cowbell_sound.play()
        print("[COWBELL] More Cowbell!!! 🚨🔔🐄")

    def _send_action(self, action):

        try:
            if action in ("start_npc_stream", "stop_npc_stream", "idle"):
                print(f"[NPC] 🚫 Blocked invalid action from _send_action(): '{action}'")
                return  # 🚫 Stop misrouted start/stop calls here

            uid = self.node.get("universal_id")
            token = str(uuid.uuid4())
            print(f"[NPC] Sending action '{action}' to agent {uid}")

            pk = Packet()
            payload = {
                "target_agent": uid,
                "session_id": self.session_id,
                "token": token,
                "return_handler": "npc_simulator.gameboard.response",
                "action": action
            }

            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "npc.swarm.control",
                    "payload": payload
                }
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk
            )
        except Exception as e:
            emit_gui_exception_log("Gameboard._send_action", e)

    def start_stream_clicked(self):
        self._send_command("cmd_start_npc_stream", service="npc.swarm.stream.start")

    def stop_stream_clicked(self):
        self._send_command("cmd_stop_npc_stream", service="npc.swarm.stream.stop")


    @pyqtSlot()
    def _drain_frame_queue(self):
        if not self._frame_queue:
            return

        # get the latest frame (drop older ones if multiple stacked)
        player_pos, npc_list = self._frame_queue.pop()
        self._frame_queue.clear()  # discard leftovers

        # safe draw
        self._update_grid_safe(player_pos, npc_list)

    @pyqtSlot()
    def _drain_frame_queue(self):
        try:
            if not self._frame_queue:
                return

            # take the newest frame, discard the rest
            player_pos, npc_list = self._frame_queue.pop()
            self._frame_queue.clear()

            # safe draw
            self._update_grid_safe(player_pos, npc_list)
            self.update()
            self.repaint()

        except Exception as e:
            emit_gui_exception_log("Gameboard._drain_frame_queue", e)

    def _handle_gameboard_response(self, session_id, channel, source, payload, ts=None, **_):
        try:
            data = payload.get("content", {})
            #print(f"[GAMEBOARD] 📨 Session={session_id} Data={data}")

            player_pos = data.get("player_pos", (0, 0))
            npc_list = data.get("npc_list", [])
            self.last_player_pos = player_pos
            self.last_npc_list = npc_list
            self.has_drawn = True

            # enqueue frame
            self._frame_queue.append((player_pos, npc_list))

            # schedule the consumer to run on GUI thread
            QMetaObject.invokeMethod(self, "_drain_frame_queue", Qt.ConnectionType.QueuedConnection)

        except Exception as e:
            emit_gui_exception_log("Gameboard._handle_gameboard_response", e)


    def showEvent(self, event):

        try:
            super().showEvent(event)
            if getattr(self, "has_drawn", False):  # only redraw if a real frame exists
                self._update_grid(self.last_player_pos, self.last_npc_list)
        except Exception as e:
            emit_gui_exception_log("Gameboard.showEvent", e)

    def _send_command(self, cmd_handler, service, extra_payload=None):
        try:
            uid = self.node.get("universal_id")
            token = str(uuid.uuid4())

            pk = Packet()
            payload = {
                "target_agent": uid,
                "session_id": self.session_id,
                "return_handler": "npc_simulator.gameboard.response"
            }

            if extra_payload:
                payload.update(extra_payload)

            if cmd_handler == "cmd_start_npc_stream":
                payload["token"] = token

            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": service,
                    "payload": payload
                }
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk
            )

        except Exception as e:
            emit_gui_exception_log("Gameboard._send_command", e)

