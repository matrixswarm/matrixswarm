from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.registry.object_classes import EDITOR_REGISTRY

class ConstraintValidator:
    """Commander Edition — validates editor-backed constraints."""

    def __init__(self):
        vcs = VaultCoreSingleton.get()
        self.registry_store = vcs.get_store("registry")

    def validate(self, constraint):
        cls = constraint.get("class")
        serial = constraint.get("serial")
        if not cls or not serial:
            return False, f"{cls or '?'} missing serial"

        editor_cls = EDITOR_REGISTRY.get(cls)
        if not editor_cls:
            return False, f"No editor for {cls}"

        ns = self.registry_store.get_namespace(cls)
        obj = ns.get(serial)
        if not obj:
            return False, f"{cls}:{serial} not found in registry"

        try:
            editor = editor_cls(new_conn=False)
            editor.on_load(obj)
            ok, msg = editor.is_validated()
            return ok, msg or "ok"
        except Exception as e:
            return False, f"{cls}:{serial} validation crash: {e}"
