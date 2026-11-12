"""Descriptor-anchored packet directory resolution for MatrixOS."""
import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from core.python_core.safe_paths import _component, child_directory, open_base, open_beneath, runtime_directory


@contextmanager
def packet_directory(location, address=None, drop=None, *, create=False, root_fd=None):
    if not isinstance(location, (str, os.PathLike)) or not os.fspath(location):
        raise ValueError("Packet location is required")
    raw = Path(location)
    if ".." in raw.parts:
        raise ValueError("Packet location cannot contain parent traversal")
    path = Path(os.path.abspath(raw))
    parts = path.parts
    match = None
    for i in range(1, len(parts) - 4):
        if parts[i:i + 2] == ("universes", "runtime") and parts[i + 4] == "comm":
            match = i
    with ExitStack() as stack:
        if root_fd is not None:
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                raise ValueError("Packet root descriptor is not a directory")
            root = os.dup(root_fd)
            stack.callback(os.close, root)
        elif match is not None:
            base = Path(*parts[:match])
            root = stack.enter_context(runtime_directory(base, parts[match + 2], parts[match + 3], "comm"))
            tail = parts[match + 5:]
            for name in tail:
                root = stack.enter_context(child_directory(root, _component(name), create=create))
        else:
            # The caller explicitly selects generic (non-runtime) packet roots.
            root = open_base(path, create=create)
            stack.callback(os.close, root)
        if address is not None:
            root = stack.enter_context(child_directory(root, _component(address), create=create))
        if drop:
            root = stack.enter_context(child_directory(root, _component(drop), create=create))
        # open_base returns O_PATH; receive/list operations need a readable FD.
        readable = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=root)
        stack.callback(os.close, readable)
        yield readable


def open_packet(directory_fd, name):
    """Open only an ordinary, unshared packet; never follow links/mounts."""
    fd = open_beneath(directory_fd, _component(name), os.O_RDONLY | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Unsafe packet file")
        return fd
    except BaseException:
        os.close(fd)
        raise
