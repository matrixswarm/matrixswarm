import importlib
import inspect
import pathlib

def auto_discover_editors():
    """
    Discover editor classes from object_classes/editors.
    Filename becomes constraint type.
    """
    base_path = (
        pathlib.Path(__file__)
        .parent.parent
        / "registry"
        / "object_classes"
        / "editors"
    )
    registry = {}

    for file in base_path.glob("*.py"):
        if file.name == "__init__.py":
            continue

        module_name = f"matrix_gui.registry.object_classes.editors.{file.stem}"
        module = importlib.import_module(module_name)

        # Find classes defined in this module
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Only classes defined here (avoid base classes from imports)
            if obj.__module__ == module_name:
                proto = file.stem.lower()
                registry[proto] = obj

    return registry


def auto_discover_providers():
    """
    Discover provider classes from object_classes/providers.
    Filename becomes constraint type.
    """
    base_path = (
        pathlib.Path(__file__)
        .parent.parent
        / "registry"
        / "object_classes"
        / "providers"
    )
    registry = {}

    for file in base_path.glob("*.py"):
        if file.name == "__init__.py":
            continue

        module_name = f"matrix_gui.registry.object_classes.providers.{file.stem}"
        module = importlib.import_module(module_name)

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module_name:
                continue

            # Skip abstract base classes
            if inspect.isabstract(obj):
                continue

            proto = file.stem.lower()
            registry[proto] = obj()

    return registry
