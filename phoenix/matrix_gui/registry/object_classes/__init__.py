from ..registry_loader import auto_discover_editors, auto_discover_providers

EDITOR_REGISTRY   = auto_discover_editors()
PROVIDER_REGISTRY = auto_discover_providers()
__all__ = ["EDITOR_REGISTRY", "PROVIDER_REGISTRY"]