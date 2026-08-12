
# ---------------------------------------------------------
# Constraint Row Widget
# ---------------------------------------------------------
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.registry.object_classes import EDITOR_REGISTRY, PROVIDER_REGISTRY
from .registry_constraint_handler import RegistryConstraintHandler
class ConstraintResolver:
    """Commander Edition – Unified constraint resolver."""

    def __init__(self):
        self.vcs = VaultCoreSingleton.get()
        self.registry = self.vcs.get_store("registry")

        # registry-backed providers
        self.resolvers = {
            cls: RegistryConstraintHandler(cls, provider, self.registry)
            for cls, provider in PROVIDER_REGISTRY.items()
        }

    # ----------------------------------------------------------
    # classification helpers
    # ----------------------------------------------------------
    def is_autogen(self, cls_name):
        editor_cls = EDITOR_REGISTRY.get(cls_name)
        if not editor_cls:
            return False
        try:
            instance = editor_cls()
            return hasattr(instance, "is_autogen") and instance.is_autogen()
        except Exception:
            return False

    def get_editor(self, cls_name):

        try:
            editor_cls = EDITOR_REGISTRY.get(cls_name)
            if not editor_cls:
                return False
            try:
                instance = editor_cls()
                return instance
            except Exception:
                return False
        except Exception as e:
            pass


    def has_editor(self, cls_name):
        return cls_name in EDITOR_REGISTRY

    def is_registry_based(self, cls_name):
        return cls_name in PROVIDER_REGISTRY

    def is_connection(self, class_name: str) -> bool:
        """
        Commander Edition — True if the given constraint class is a connection type.
        Checks editor registry for static is_connection() flag.
        """
        r=False
        try:

            editor_cls = EDITOR_REGISTRY.get(class_name)

            if editor_cls:
                cls = editor_cls()
                r = cls.is_connection()

        except Exception as e:
            print(f"[RESOLVER][WARN] is_connection check failed for {class_name}: {e}")
        finally:
            return r

    # ----------------------------------------------------------
    def get(self, cname):
        """
        Commander Edition: unified resolver
        Always return an editor class (registry or autogen).
        """
        editor_cls = EDITOR_REGISTRY.get(cname)
        if editor_cls:
            return editor_cls
        print(f"[RESOLVER][WARN] No editor found for constraint: {cname}")
        return None


    __getitem__ = get

    def __contains__(self, key):
        return key in self.resolvers or key in self._autogen.all()