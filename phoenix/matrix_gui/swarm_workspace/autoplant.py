# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition — Unified Autoplant Routine
from .cls_lib.agent.agent_node import AgentNode
from .agent_item import AgentItem


def autoplant(scene, meta, saved=None):
    """
    Create the AgentNode (model) and AgentItem (view)
    and place it onto the scene.
    """

    # Build model
    node = AgentNode.from_saved(meta, saved) if saved else AgentNode(meta)

    # Build view
    item = AgentItem(node)
    px, py = node.pos["x"], node.pos["y"]
    item.setPos(px, py)

    # Add to scene
    scene.addItem(item)

    return item
