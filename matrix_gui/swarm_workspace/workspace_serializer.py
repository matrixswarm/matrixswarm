# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Turns scene into workspace JSON
from pathlib import Path
import json

def collect_scene_nodes(scene):
    """
    Return list of AgentNode.get_node() from all items in scene.
    """
    workspace = getattr(scene, "workspace", None)
    controller = getattr(workspace, "controller", None)
    if controller is not None and hasattr(controller, "serialize"):
        return controller.serialize()

    nodes = []
    for item in scene.items():
        if hasattr(item, "node"):
            nodes.append(item.node.get_node())
    return nodes

def save_to_file(path, nodes):
    Path(path).write_text(json.dumps(nodes, indent=2))
