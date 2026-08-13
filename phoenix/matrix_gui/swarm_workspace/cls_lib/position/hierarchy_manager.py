class HierarchyManager:
    """
    Computes depth, validates parent assignment, and enforces Matrix root rule.
    """

    ROOT_NAME = "matrix"

    @staticmethod
    def compute_depth(node, lookup):
        """
        node: {"name":..., "parent":...}
        lookup: dict name -> node
        """
        depth = 0
        parent = node.get("parent")

        while parent:
            parent_node = lookup.get(parent)
            if not parent_node:
                break
            depth += 1
            parent = parent_node.get("parent")

        return depth

    @staticmethod
    def validate(node, lookup):
        name = node["name"]
        parent = node.get("parent")

        # Matrix must be the ONLY root
        if name == HierarchyManager.ROOT_NAME:
            return parent in (None, "", "matrix")

        # All other agents must have exactly one parent
        if not parent:
            return False

        # Parent must exist
        return parent in lookup
