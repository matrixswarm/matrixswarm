from copy import deepcopy
from matrix_gui.registry.object_classes import EDITOR_REGISTRY
from ..constraint.autogen_constraint import AutoGenConstraint
class Constraint:
    """
    Live representation of a constraint instance during deploy/compile.
    Carries its handler/editor, fields, and behaviour.
    """
    def __init__(self, cls_name, handler, meta, agent=None):
        self.cls_name = cls_name              # e.g. 'packet_signing'
        self.handler = handler                # editor/autogen handler
        self.meta = deepcopy(meta or {})      # raw constraint dict from node
        self.agent = agent                    # reference to owning AgentNode
        self.is_autogen = self.meta.get("auto", False)
        self.required = self.meta.get("required", True)
        self.serial = self.meta.get("serial")
        self.inject_in_connection = self.meta.get("raw", {}).get("inject_in_connection", False)
        self.path = []
        self.fields = {}

    # --------------------------------------------------------
    # Behavioural helpers
    # --------------------------------------------------------
    def get_constraint_name(self):
        return self.cls_name
    def get_fields(self):
        return self.fields
    def get_meta(self):
        return self.meta
    def inject_into_connection(self):
        return bool(self.inject_in_connection)

    def resolve(self):
        if self.is_autogen:
            result = self.handler.resolve(self.agent)
            self.fields = result.get("full", result)
            self.path = AutoGenConstraint.get_path(self.cls_name, scope="directive")
        else:
            editor_cls = EDITOR_REGISTRY.get(self.cls_name)
            editor = editor_cls(new_conn=False)
            obj = self.handler.registry.get_namespace(self.cls_name).get(self.serial) or {}
            editor.on_load(obj)
            self.fields = editor.deploy_fields()
            self.path = editor.get_directory_path()

        # HARD GUARANTEE: path is ALWAYS a list[str]
        if isinstance(self.path, str):
            self.path = [p for p in self.path.split("/") if p]

        elif not isinstance(self.path, list):
            self.path = []

        # REMOVE leading "config" ONCE
        if self.path and self.path[0] == "config":
            self.path = self.path[1:]

        return self

    def get_editor(self):
        return self.handler

    def validate(self):
        """Raise if a required manual constraint is missing serial."""
        if not self.is_autogen and self.required and not self.serial:
            raise ValueError(
                f"[CONSTRAINT][{self.cls_name}] Missing serial assignment."
            )
        return True

    def set_serial(self, serial):
        self.serial = serial
        self.meta["serial"] = serial

    # --------------------------------------------------------
    # Data access helpers
    # --------------------------------------------------------
    def get_field(self, key, default=None):
        """Access a field from deploy/autogen data."""
        return self.fields.get(key, default)

    def to_dict(self):
        """Minimal export used for DirectiveCompiler or logs."""
        return {
            "class": self.cls_name,
            "is_autogen": self.is_autogen,
            "serial": self.serial,
            "path": self.path,
            "fields": self.fields,
        }
