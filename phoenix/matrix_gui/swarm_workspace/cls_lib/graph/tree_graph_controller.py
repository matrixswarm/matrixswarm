# Commander Edition – TreeGraphController
# Full tree-based graph engine for Swarm Workspace
import time
import uuid
import hashlib
from PyQt6.QtWidgets import QGraphicsLineItem, QMessageBox, QMenu
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPen, QColor
from matrix_gui.swarm_workspace.autoplant import autoplant
from PyQt6.QtCore import QTimer
class TreeGraphController:
    """
    Commander Edition – Central controller that manages:
      • AgentItems placement
      • Parent–child relationships
      • Drag-to-reparent logic
      • Auto-tree layout
      • Auto-drawn edges
      • CRUD (cut, copy, paste, delete)
      • Inspector integration
      • Workspace load/save
    """

    # ----------------------------------------------
    # INIT
    # ----------------------------------------------
    def __init__(self, scene, inspector):
        self.scene = scene
        self.inspector = inspector

        self.nodes = {}
        self.edges = []
        self.clipboard = None

        # SAVE original event handlers
        self._orig_mouse_press = scene.mousePressEvent
        self._orig_mouse_release = scene.mouseReleaseEvent

        # OVERRIDE with our handlers
        scene.mousePressEvent = self._mouse_press
        scene.mouseReleaseEvent = self._mouse_release

        self.dragging_item = None
        self.drop_target = None

        self._orig_mouse_move = scene.mouseMoveEvent
        scene.mouseMoveEvent = self._mouse_move


    # ----------------------------------------------
    # NODE REGISTRATION
    # ----------------------------------------------
    def register_item(self, item):
        """
        Called from autoplant() or workspace loader.
        """
        gid = item.node.get_graph_id()
        self.nodes[gid] = item

        # attach right-click context menu
        item.contextMenuEvent = lambda evt, i=item: self._show_context_menu(evt, i)

    # ----------------------------------------------
    # CONTEXT MENU
    # ----------------------------------------------
    def _show_context_menu(self, event, item):
        menu = QMenu()

        # Inspect
        inspect_action = menu.addAction("Inspect")
        inspect_action.triggered.connect(lambda: self.inspector.load(item.node))

        # Reparent submenu
        parent_menu = menu.addMenu("Reparent To")
        for gid, target in self.nodes.items():
            if gid == item.node.get_graph_id():
                continue
            parent_menu.addAction(target.node.get_name(),
                                  lambda checked=False, t=target: self.reparent(item, t))

        # Delete
        if item.node.get_name().lower() != "matrix":
            del_action = menu.addAction("Delete")
            del_action.triggered.connect(lambda: self.delete_node(item))

        menu.exec(event.screenPos())

    # ----------------------------------------------
    # Add Item
    # ----------------------------------------------
    def add_agent(self, meta, drop_pos, view):
        """
        Commander Edition — Handles full agent insertion pipeline.
        - Spawns the agent from meta
        - Finds correct parent (hovered or Matrix)
        - Sets parent graph_id
        - Registers node in controller
        - Normalizes orphans and redraws
        Returns the created AgentItem
        """
        try:
            # Spawn new item
            item = autoplant(self.scene, meta)
            self.register_item(item)

            # Find hovered item under drop position
            hovered = self.scene.itemAt(drop_pos, view.transform())

            # Determine parent graph_id
            if hasattr(hovered, "node"):
                parent_gid = hovered.node.get_graph_id()
            else:
                parent_gid = self.get_graph_id("matrix")

            # Assign parent
            item.node.set_parent(parent_gid)

            # Normalize and refresh visuals
            self.normalize_orphans()
            self.relayout()
            self.redraw_edges()


            print(f"[TREE] Added agent '{item.node.get_name()}' under parent {parent_gid}")
            return item

        except Exception as e:
            print(f"[TREE][ERROR] add_agent failed: {e}")
            return None

    def get_graph_id(self, name="matrix"):
        """
        Commander Edition – Safe lookup for a node's graph_id by name.

        • Normalizes case and trims whitespace
        • Handles missing or None names gracefully
        • Prints a warning if the agent is not found
        """
        if not name or not isinstance(name, str):
            print("[TREE][WARN] get_graph_id called without valid name.")
            return None

        target = name.strip().lower()

        for item in self.nodes.values():
            node_name = item.node.get_name().strip().lower()
            if node_name == target:
                return item.node.get_graph_id()

        print(f"[TREE][WARN] No agent found with name '{target}'.")
        return None

    # ----------------------------------------------
    # DELETE
    # ----------------------------------------------
    def delete_node(self, item):
        """
        Recursively deletes an agent and all of its descendants.

        - Prompts user if the node has children.
        - Prevents deletion of Matrix.
        - Updates inspector after deletion.
        """
        node = item.node
        name = node.get_name()

        # Prevent Matrix deletion
        if name.lower() == "matrix":
            QMessageBox.warning(None, "Cannot Delete Matrix",
                                "Matrix is the root of the swarm and cannot be deleted.")
            return

        # Collect all descendants
        gid = node.get_graph_id()
        descendants = [n for n in self.nodes.values() if self._is_descendant(n.node, gid)]

        # Confirm if this is a branch delete
        if descendants:
            count = len(descendants)
            reply = QMessageBox.question(
                None,
                "Delete Branch?",
                f"'{name}' has {count} child agent(s).\n\n"
                "Deleting this agent will also delete ALL of its descendants.\n\n"
                "Do you want to proceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Perform recursive delete
        to_remove = descendants + [item]
        for n in to_remove:
            gid = n.node.get_graph_id()
            try:
                self.scene.removeItem(n)
            except Exception:
                pass
            self.nodes.pop(gid, None)

        # Notify Inspector — let it decide what to do
        if hasattr(self.inspector, "on_agents_deleted"):
            self.inspector.on_agents_deleted(to_remove)

        # Refresh visuals
        QTimer.singleShot(0, self._post_delete_redraw)

        # Update Inspector (clear or reload Matrix)
        try:
            matrix = next((i for i in self.nodes.values()
                           if i.node.get_name().lower() == "matrix"), None)
            if matrix:
                self.inspector.load(matrix.node)
            else:
                self.inspector.load(None)
        except Exception:
            pass

    def _is_descendant(self, node, ancestor_gid):
        """
        Returns True if node’s parent chain leads to ancestor_gid.
        """
        parent = node.get_parent()
        while parent:
            if parent == ancestor_gid:
                return True
            parent_item = self.nodes.get(parent)
            parent = parent_item.node.get_parent() if parent_item else None
        return False

    def _collect_subtree(self, item):
        """
        Returns a list of all AgentItems in this item's subtree,
        including the item itself.
        """
        result = [item]
        children = self.get_children(item)
        for c in children:
            result.extend(self._collect_subtree(c))
        return result

    # ----------------------------------------------
    # DRAG / DROP RE-PARENT LOGIC
    # ----------------------------------------------
    def _mouse_press(self, event):

        pos = event.scenePos()
        clicked = self.scene.itemAt(pos, self.scene.views()[0].transform())

        if hasattr(clicked, "node"):
            # Block Matrix from dragging entirely
            if clicked.node.get_name().lower() == "matrix":
                self.dragging_item = None
                return self._orig_mouse_press(event)

            self.dragging_item = clicked

        # Call original scene press handler
        if self._orig_mouse_press:
            self._orig_mouse_press(event)

    def _mouse_release(self, event):
        if self.dragging_item and self.drop_target:
            self.reparent(self.dragging_item, self.drop_target)

        self.dragging_item = None
        self.drop_target = None
        self._orig_mouse_release(event)

    def _mouse_move(self, event):
        pos = event.scenePos()
        hovered = self.scene.itemAt(pos, self.scene.views()[0].transform())

        # Default: no drop target
        self.drop_target = None

        # Only treat AgentItems as targets
        if hasattr(hovered, "node"):
            self.drop_target = hovered

        # Call original
        if self._orig_mouse_move:
            self._orig_mouse_move(event)

    def reparent(self, item, new_parent_item):
        """Assigns new parent to a node; no child arrays maintained."""
        if not item or not hasattr(item, "node") or not new_parent_item:
            return

        # prevent cycles
        if not self._valid_reparent(item, new_parent_item):
            return

        # just change the parent
        item.node.set_parent(new_parent_item.node.get_graph_id())

        # redraw visuals
        self.relayout()
        self.redraw_edges()

        # optional inspector reload
        try:
            self.inspector.load(item.node)
        except Exception:
            pass

    def normalize_orphans(self):
        """
        Commander Edition:
        Ensure no dangler agents exist.
        Any node without a valid parent is adopted by Matrix.
        """

        # Find Matrix's graph ID
        matrix_gid = None
        for item in self.nodes.values():
            if item.node.get_name().lower() == "matrix":
                matrix_gid = item.node.get_graph_id()
                break

        if not matrix_gid:
            print("[TREE] No matrix found during normalize_orphans()")
            return

        # Adopt all orphans
        for gid, item in self.nodes.items():
            n = item.node
            parent = n.get_parent()

            # Matrix never gets a parent
            if n.get_name().lower() == "matrix":
                n.set_parent(None)
                continue

            # ORPHAN CONDITIONS:
            if (
                    parent is None or
                    parent not in self.nodes or  # parent doesn't exist
                    parent == gid or  # self-parent
                    parent == "matrix"  # legacy old-style literal parent
            ):
                n.set_parent(matrix_gid)

    def _normalize_parent_ids(self):
        """
        Fixes old workspaces where parent == 'matrix' instead of the graph_id.
        """
        # find the real Matrix id
        matrix_gid = None
        for item in self.nodes.values():
            if item.node.get_name().lower() == "matrix":
                matrix_gid = item.node.get_graph_id()

        if not matrix_gid:
            return

        # fix all children referring to literal "matrix"
        for item in self.nodes.values():
            if item.node.get_parent() == "matrix":
                item.node.set_parent(matrix_gid)

    def _valid_reparent(self, item, new_parent_item):
        if not new_parent_item:
            return False

        if item == new_parent_item:
            return False

        # cycle detection
        parent = new_parent_item.node.get_graph_id()
        child = item.node.get_graph_id()
        while parent:
            if parent == child:
                return False
            p = self.nodes[parent].node.get_parent()
            parent = p
        return True

    # ----------------------------------------------
    # AUTO-LAYOUT ENGINE
    # ----------------------------------------------
    def relayout(self):
        # Find root
        root = None
        for node in self.nodes.values():
            if node.node.get_name().lower() == "matrix":
                root = node
                break

        if not root:
            return

        # Build a hashmap: level → list of nodes
        levels = {}
        self._collect_levels(root, 0, levels)

        # Layout each level horizontally centered
        spacing_x = 220
        spacing_y = 150

        for level, items in levels.items():
            count = len(items)
            start_x = -((count - 1) * spacing_x) / 2

            for i, item in enumerate(items):
                item.setPos(start_x + i * spacing_x, level * spacing_y)

    def _collect_levels(self, item, level, levels):
        if level not in levels:
            levels[level] = []
        levels[level].append(item)

        for c in self.get_children(item):
            self._collect_levels(c, level + 1, levels)

    def _layout_subtree(self, item, x, y, level):
        item.setPos(x, y)

        children = self.get_children(item)

        # position children horizontally spaced
        spacing_x = 250
        spacing_y = 140

        start_x = x - (len(children) - 1) * spacing_x / 2

        for i, child in enumerate(children):
            child_x = start_x + i * spacing_x
            child_y = y + spacing_y
            self._layout_subtree(child, child_x, child_y, level + 1)

    # ----------------------------------------------
    # TREE HELPERS
    # ----------------------------------------------
    def get_children(self, item):
        cid = item.node.get_graph_id()
        return [self.nodes[nid] for nid in self.nodes
                if self.nodes[nid].node.get_parent() == cid]

    # ----------------------------------------------
    # REDRAW EDGES
    # ----------------------------------------------
    def _post_delete_redraw(self):

        self.relayout()
        self.redraw_edges()
        self.scene.invalidate(self.scene.sceneRect())
        self.scene.update()



    def redraw_edges(self):
        # HARD purge: remove ALL line items from the scene
        for item in list(self.scene.items()):
            if isinstance(item, QGraphicsLineItem):
                try:
                    self.scene.removeItem(item)
                except:
                    pass

        self.edges.clear()

        pen = QPen(QColor("#777"))
        pen.setWidth(2)

        # rebuild clean edges only
        for gid, item in self.nodes.items():
            parent_id = item.node.get_parent()

            if not parent_id:
                continue

            parent = self.nodes.get(parent_id)
            if not parent:
                continue

            p1 = QPointF(parent.x() + 80, parent.y() + 60)
            p2 = QPointF(item.x() + 80, item.y())

            line = QGraphicsLineItem(p1.x(), p1.y(), p2.x(), p2.y())
            line.setPen(pen)
            self.scene.addItem(line)
            self.edges.append(line)

    # ----------------------------------------------
    # SAVE / LOAD SUPPORT
    # ----------------------------------------------
    def export_agents(self):
        agents = []
        for gid, wrapped in self.nodes.items():
            node = wrapped.node
            agents.append({
                "name": node.get_name(),
                "universal_id": node.get_universal_id(),
                "graph_id": node.get_graph_id(),
                "serial": str(hashlib.sha256(f"{uuid.uuid4()}-{time.time()}".encode()).hexdigest()),
                "parent": node.get_parent(),
                "constraints": node.get_constraints(),
                "connections": node.get_connections(),
                "params": node.get_params(),
            })
        return agents

    def export_agent_tree(self):
        """Rebuild the entire tree dynamically from parent links."""
        agents = {gid: n.node.get_node() for gid, n in self.nodes.items()}
        for a in agents.values():
            a["children"] = []

        # derive children dynamically
        for gid, agent in agents.items():
            parent = agent.get("parent")
            if parent and parent in agents:
                agents[parent]["children"].append(gid)

        # find root (Matrix)
        root_gid = next((gid for gid, a in agents.items()
                         if a.get("parent") is None or a["name"].lower() == "matrix"), None)

        return agents, root_gid

    def serialize(self):
        """Return list of all node dictionaries for saving into workspace."""
        return [item.node.get_node() for item in self.nodes.values()]

    def load(self, items):
        """Load nodes from workspace data."""
        self.nodes.clear()
        self.edges.clear()

        for node_data in items:
            meta = self._load_meta(node_data["name"])
            item = self._spawn(meta)
            item.node = item.node.from_saved(meta, node_data)
            self.register_item(item)

        self.relayout()
        self.redraw_edges()

    # (helpers)
    def _load_meta(self, name):
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "agents_meta" / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _spawn(self, meta):

        item = autoplant(self.scene, meta)
        return item
