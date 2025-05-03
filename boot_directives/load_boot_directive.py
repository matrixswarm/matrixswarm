import os
import sys
from dotenv import load_dotenv

# Setup the base path and environment (run only once during import)
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BASE not in sys.path:
    sys.path.insert(0, BASE)

# Load environment from the project root
load_dotenv(os.path.join(BASE, ".env"))

def load_boot_directive(name="default"):
    """
    Dynamically loads and returns a boot directive by its name.

    :param name: Name of the directive to load (default is "default").
    :type name: str
    :return: The `matrix_directive` dictionary from the requested module.
    :raises ModuleNotFoundError: If the module cannot be found.
    :raises AttributeError: If the module does not contain `matrix_directive`.
    """
    try:
        # Verify the requested directive file exists
        module_path = os.path.join(BASE, "boot_directives", f"{name}.py")
        if not os.path.isfile(module_path):
            raise ModuleNotFoundError(f"Directive file '{module_path}' does not exist.")

        # Import the directive module dynamically
        mod_path = f"boot_directives.{name}"
        directive_mod = __import__(mod_path, fromlist=["matrix_directive"])

        # Ensure the directive has the required `matrix_directive` attribute
        if not hasattr(directive_mod, "matrix_directive"):
            raise AttributeError(f"Directive module '{name}' does not contain 'matrix_directive'.")

        # Return the loaded directive
        return directive_mod.matrix_directive

    except ModuleNotFoundError as e:
        print(f"[BOOTLOADER][ERROR] Could not find directive '{name}': {e}")
        sys.exit(1)
    except AttributeError as e:
        print(f"[BOOTLOADER][ERROR] Invalid directive '{name}': {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[BOOTLOADER][ERROR] Unexpected error while loading directive '{name}': {e}")
        sys.exit(1)
