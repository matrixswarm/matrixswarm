"""Explicit terminal contracts. Unknown methods and fields are rejected."""
from copy import deepcopy

# These are ordinary terminal operations; no MCP adapter is required.
OPERATIONS = {
    "bridge.status": ({}, {}, False, "Show assignment state and available operations."),
    "tools.describe": ({}, {}, False, "Discover parameters, approval requirements, and next steps."),
    "deployment.list": ({}, {}, False, "List only deployments selected by the operator."),
    "deployment.launch": ({"deployment_id": str}, {"request_id": str}, True,
                          "Request a Phoenix connection session. This does not deploy or boot a universe."),
    "session.list": ({}, {}, False, "List active sessions within the assignment."),
    "agent.list": ({"deployment_id": str}, {}, False, "List prepared agents without their credentials."),
    "agent.tree": ({"session_id": str}, {"refresh": bool}, False,
                   "Read the live tree; only assigned agents are returned."),
    "agent.describe": ({"deployment_id": str, "agent_id": str}, {}, False,
                       "Show permitted saved settings and their validation rules."),
    "agent.config.set": ({"deployment_id": str, "agent_id": str, "changes": dict, "request_id": str}, {}, True,
                         "Request a saved vault configuration edit. Does not change a running agent; apply through a later deployment."),
    "agent.restart": ({"session_id": str, "agent_id": str, "request_id": str}, {}, True,
                      "Request restart of one running agent only. Interrupts its current work; does not apply saved vault edits."),
    "agent.logs.start": ({"session_id": str, "agent_id": str}, {"follow": bool}, False,
                         "Subscribe to redacted agent logs; returns a subscription_id."),
    "agent.logs.read": ({"subscription_id": str}, {"after": int, "limit": int}, False,
                        "Read with an absolute cursor. A gap means older lines were discarded."),
    "session.alerts": ({"session_id": str}, {"after": int, "limit": int}, False,
                       "Read redacted session alerts collected while this assignment is enabled."),
    "investigation.list": ({}, {}, False, "List saved investigations for the current assignment only."),
    "investigation.open": ({"investigation_id": str, "deployment_id": str, "agent_id": str}, {}, False,
                           "Save a fixed tool selection in the encrypted vault. No remote action or credentials."),
    "investigation.resume": ({"investigation_id": str}, {}, False,
                             "Resume a saved selection; show buffer gaps/unavailability. Never auto-connects."),
    "investigation.attach": ({"investigation_id": str, "session_id": str}, {"reset": bool}, False,
                             "Start a live log review window for a running assigned session. Explicit reset acknowledges lost buffers."),
    "investigation.read": ({"investigation_id": str, "stream": str}, {"limit": int}, False,
                           "Read logs or alerts from the saved cursor without advancing it; returns a review receipt."),
    "investigation.ack": ({"investigation_id": str, "receipt": str}, {}, False,
                          "Save only the reviewed position from an issued receipt. Does not archive evidence."),
    "action.status": ({"request_id": str}, {}, False,
                      "Check the operator decision and dispatch result. Never automatically retry an uncertain action."),
}
CONFIG_FIELDS = {
    "matrix_ssh": {
        "poll_interval": {"type": "integer", "minimum": 1, "maximum": 3600,
                          "default": 1, "description": "Seconds between durable inbox checks."},
        "batch_limit": {"type": "integer", "minimum": 1, "maximum": 128,
                        "default": 32, "description": "Maximum packets processed per poll."},
    },
}


def validate_call(method, params):
    if method not in OPERATIONS:
        raise ValueError("Operation unavailable. Use tools.describe for permitted operations.")
    if not isinstance(params, dict):
        raise ValueError("Parameters must be an object.")
    required, optional, _, _ = OPERATIONS[method]
    if set(params) - (set(required) | set(optional)) or set(required) - set(params):
        raise ValueError("Missing or unknown parameters. Use tools.describe for the exact schema.")
    for key, value in params.items():
        expected = (required | optional)[key]
        if type(value) is not expected:
            raise ValueError(f"{key} has the wrong type.")
        if expected is str and (not value or len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError(f"{key} must be a nonempty identifier of at most 128 characters.")
        if key in {"after", "limit"} and value < 0:
            raise ValueError(f"{key} must be nonnegative.")


def describe_operations():
    types = {str: "string", bool: "boolean", dict: "object", int: "integer"}
    return [{
        "name": name, "description": description, "operator_approval": approval,
        "parameters": {"required": {k: types[v] for k, v in required.items()},
                       "optional": {k: types[v] for k, v in optional.items()},
                       "additional_properties": False},
        "hint": ("Keep request_id unchanged when checking or retrying this exact request. "
                 "Poll action.status; only the operator can approve in Phoenix.") if approval
                else "Use identifiers returned by this assignment.",
    } for name, (required, optional, approval, description) in OPERATIONS.items()]


def config_surface(agent):
    schema = deepcopy(CONFIG_FIELDS.get(agent.get("name"), {}))
    config = agent.get("config") if isinstance(agent.get("config"), dict) else {}
    values = {}
    for name, field in schema.items():
        value = config.get(name, field["default"])
        # Never expose arbitrary imported strings through an ostensibly numeric field.
        values[name] = value if type(value) is int and field["minimum"] <= value <= field["maximum"] else None
    return {"values": values, "fields": schema, "scope": "saved_deployment",
            "hint": "Only listed fields are editable. Null means the saved value needs operator correction."}


def validate_changes(agent, changes):
    schema = CONFIG_FIELDS.get(agent.get("name"), {})
    if not changes or set(changes) - set(schema):
        raise ValueError("Only the fields returned by agent.describe can be changed.")
    for name, value in changes.items():
        field = schema[name]
        if type(value) is not int or not field["minimum"] <= value <= field["maximum"]:
            raise ValueError(f"{name} must be an integer from {field['minimum']} to {field['maximum']}.")
    return deepcopy(changes)


class CursorBuffer:
    """Bounded stream with stable absolute positions, including explicit gaps."""
    def __init__(self, capacity=2000):
        self.capacity = capacity
        self.items = []
        self.start = 0

    def append(self, items):
        self.items.extend(items)
        dropped = max(0, len(self.items) - self.capacity)
        if dropped:
            del self.items[:dropped]
            self.start += dropped

    def read(self, after=0, limit=100):
        end = self.start + len(self.items)
        if after > end:
            raise ValueError("Cursor is beyond this stream. Use after=0 after opening a new assignment.")
        position = max(after, self.start)
        items = self.items[position-self.start:position-self.start+max(1, min(limit, 200))]
        return {"items": deepcopy(items), "next_cursor": position + len(items),
                "oldest_cursor": self.start, "gap": after < self.start, "end_cursor": end}
