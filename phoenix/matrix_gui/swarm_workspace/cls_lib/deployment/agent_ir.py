class AgentIR:
    def __init__(self, gid, node, resolved_dict, children):
        self.gid = gid
        self.node = node
        self.resolved = resolved_dict  # cname → ConstraintIR
        self.children = children

    @property
    def name(self):
        return self.node["name"]

    @property
    def universal_id(self):
        return self.node["universal_id"]
