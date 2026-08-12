# Load the editor for this class
from matrix_gui.registry.object_classes import EDITOR_REGISTRY
class RegistryConstraintHandler:
    """
    Pulls data from the Registry Vault → embeds into Phoenix deployment + directive.
    """

    def __init__(self, cls_name, provider, registry):
        self.cls_name = cls_name
        self.provider = provider
        self.registry = registry

    def deploy_fields(self, cls_name, serial):
        """
        Return a clean, deploy-ready subset of fields for this constraint.
        Uses the editor's deploy_fields() to strip UI-only keys.
        """
        if not serial:
            return {}

        ns = self.registry.get_namespace(cls_name)
        obj = ns.get(serial)
        if not obj:
            return {}

        editor_cls = EDITOR_REGISTRY.get(cls_name)
        if not editor_cls:
            return obj  # fallback – raw registry object

        editor = editor_cls(new_conn=False)
        editor.on_load(obj)

        # Clean, deploy-only fields
        return editor.deploy_fields()

    def resolve(self, constraint, agent, session):
        serial = constraint.get("serial")
        if not serial:
            return None

        ns = self.registry.get_namespace(self.cls_name)
        obj = ns.get(serial)
        if not obj:
            return None

        # Deployment bundle (private)
        full = obj.copy()

        # Directive bundle (public)
        slice_ = obj.get("public", {})

        return {
            "category": "connection",
            "full": full,
            "slice": slice_
        }
