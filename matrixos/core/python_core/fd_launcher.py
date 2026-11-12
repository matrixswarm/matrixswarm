"""Execute a pinned, verified agent source file with normal script metadata."""
import os
import stat
import sys
import types


def run_agent(*, set_script_path=True):
    ready = os.environ.get("MATRIX_BOOT_READY_FD")
    if ready is not None:
        os.set_inheritable(int(ready), False)
    fd = int(os.environ.pop("MATRIX_AGENT_RUN_FD"))
    display_path = os.environ.pop("MATRIX_AGENT_RUN_PATH")
    with os.fdopen(fd, "rb") as source:
        code = compile(source.read(), display_path, "exec")
    sys.argv = [display_path, *sys.argv[1:]]
    import_fd = os.environ.pop("MATRIX_AGENT_IMPORT_FD", None)
    if import_fd is not None:
        import_fd = int(import_fd)
        if not stat.S_ISDIR(os.fstat(import_fd).st_mode):
            raise RuntimeError("Invalid trusted agent import directory")
        os.set_inheritable(import_fd, False)
        sys.path[0] = f"/proc/self/fd/{import_fd}"
    elif sys.path:
        # Embedded source without an installed trusted tree gets no writable
        # pod/current-directory import path.
        sys.path.pop(0)
    # The spawner validates this administrator-owned base and its code trees
    # before launch. Embedded agents can import MatrixOS core without adding
    # the writable pod directory back to sys.path.
    site_root = os.environ.get("SITE_ROOT")
    if not site_root or not os.path.isabs(site_root):
        raise RuntimeError("Validated MatrixOS source root is missing")
    if site_root not in sys.path:
        sys.path.insert(1 if import_fd is not None else 0, site_root)
    module = types.ModuleType("__main__")
    module.__dict__.update({"__file__": display_path, "__package__": None if set_script_path else "",
                            "__cached__": None, "__spec__": None})
    sys.modules["__main__"] = module
    exec(code, module.__dict__)


if __name__ == "__main__":
    run_agent()
