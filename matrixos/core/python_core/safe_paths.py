"""Directory-handle based path operations for Linux runtime data.

The configured base is the trust boundary: opening it permits legitimate
mounts in its ancestry, while all subsequent descent rejects symlinks and
mount crossings (including bind mounts). Unsupported kernels fail closed.
"""

import ctypes
import errno
import os
import platform
import stat
import uuid
from contextlib import contextmanager, ExitStack
from pathlib import Path

_RESOLVE_NO_XDEV = 0x01
_RESOLVE_NO_MAGICLINKS = 0x02
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
_TRAVERSE_FLAGS = getattr(os, "O_PATH", 0) | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
_SUPPORTED_ARCHES = {"x86_64", "amd64", "aarch64", "arm64", "riscv64", "ppc64le", "s390x"}


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64)]


def _component(name):
    if not isinstance(name, str) or not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
        raise ValueError("Unsafe path component")
    return name


def open_base(path, *, create=False):
    """Open a configured base without following symlinks in its ancestry."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("Secure runtime paths require Linux directory handles")
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Configured base must be an absolute path without '..'")
    fd = os.open("/", _TRAVERSE_FLAGS)
    try:
        if create:
            probe = _openat2(fd, ".", _TRAVERSE_FLAGS)
            os.close(probe)
        for part in path.parts[1:]:
            _component(part)
            try:
                child = os.open(part, _TRAVERSE_FLAGS | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o777, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, _TRAVERSE_FLAGS | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _openat2(parent_fd, name, flags, mode=0):
    if platform.system() != "Linux" or platform.machine().lower() not in _SUPPORTED_ARCHES:
        raise RuntimeError("Secure runtime paths require Linux openat2 on a supported architecture")
    # openat2 uses syscall number 437 on the explicitly listed Linux ABIs.
    how = _OpenHow(flags | getattr(os, "O_CLOEXEC", 0), mode,
                   _RESOLVE_BENEATH | _RESOLVE_NO_MAGICLINKS |
                   _RESOLVE_NO_SYMLINKS | _RESOLVE_NO_XDEV)
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(437, parent_fd, os.fsencode(name), ctypes.byref(how), ctypes.sizeof(how))
    if result < 0:
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EPERM):
            raise RuntimeError("Secure runtime paths require Linux openat2 (5.6+) permitted by the host security policy")
        raise OSError(error, os.strerror(error), name)
    return result


def open_beneath(parent_fd, name, flags=_DIR_FLAGS, mode=0):
    """Open one component without symlinks or mount crossings via openat2."""
    return _openat2(parent_fd, _component(name), flags, mode)


@contextmanager
def child_directory(parent_fd, name, *, create=False, mode=0o777, traverse_only=False):
    _component(name)
    if create:
        # Probe before mutating anything, including on old or restricted kernels.
        probe = _openat2(parent_fd, ".", _TRAVERSE_FLAGS)
        os.close(probe)
        try:
            os.mkdir(name, mode, dir_fd=parent_fd)
        except FileExistsError:
            pass
    fd = open_beneath(parent_fd, name, _TRAVERSE_FLAGS if traverse_only else _DIR_FLAGS)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def runtime_directory(base, universe, boot_id, kind, *, child=None, create_child=False):
    """Hold a verified runtime directory from the configured base downward."""
    if kind not in ("comm", "pod"):
        raise ValueError("Unknown runtime directory")
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        for name in ("universes", "runtime"):
            root = stack.enter_context(child_directory(root, name, traverse_only=True))
        for name in (universe, boot_id, kind):
            root = stack.enter_context(child_directory(root, name))
        if child is not None:
            root = stack.enter_context(child_directory(root, child, create=create_child))
        yield root


@contextmanager
def static_directory(base, universe, boot_id, kind=None, *, child=None, create_child=False):
    """Hold a verified static boot or per-agent directory."""
    if kind not in (None, "comm", "pod") or (child is not None and kind is None):
        raise ValueError("Unknown static directory")
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        for name in ("universes", "static"):
            root = stack.enter_context(child_directory(root, name, traverse_only=True))
        for name in (universe, boot_id):
            root = stack.enter_context(child_directory(root, name))
        if kind is not None:
            root = stack.enter_context(child_directory(root, kind, create=True))
        if child is not None:
            root = stack.enter_context(child_directory(root, child, create=create_child))
        yield root


def append_file_at(directory_fd, name, payload, *, mode=0o666):
    """Append only to an ordinary, single-link file beneath an open directory."""
    _component(name)
    if not isinstance(payload, bytes):
        raise TypeError("Append payload must be bytes")
    fd = open_beneath(directory_fd, name, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NONBLOCK, mode)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Unsafe append target")
        with os.fdopen(fd, "ab") as stream:
            fd = -1
            stream.write(payload)
    finally:
        if fd >= 0:
            os.close(fd)


def read_agent_source(base, lang, agent_name, ext):
    """Read installed agent source through no-link, no-cross-device handles."""
    _component(lang)
    _component(agent_name)
    _component(ext)
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        for name in ("agents", f"{lang}_core", agent_name):
            root = stack.enter_context(child_directory(root, name))
        fd = open_beneath(root, f"{agent_name}.{ext}", os.O_RDONLY | os.O_NONBLOCK)
        stack.callback(os.close, fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Unsafe agent source file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            return stream.read()


def write_file_at(directory_fd, name, payload, *, mode=0o666, durable=False, preserve_mode=True):
    """Atomically publish bytes without following links or crossing mounts.

    Existing ordinary-file modes are retained unless preserve_mode is false.
    A prior symlink, hardlink, directory, special file, or mounted file is refused.
    """
    _component(name)
    if not isinstance(payload, bytes):
        raise TypeError("Atomic payload must be bytes")
    try:
        old_fd = open_beneath(directory_fd, name, os.O_PATH | os.O_NOFOLLOW)
    except FileNotFoundError:
        old_mode = None
    else:
        try:
            info = os.fstat(old_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Unsafe existing file")
            old_mode = stat.S_IMODE(info.st_mode) if preserve_mode else None
        finally:
            os.close(old_fd)
    temporary = f".{name}.{uuid.uuid4().hex}.tmp"
    fd = open_beneath(directory_fd, temporary,
                      os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                      old_mode if old_mode is not None else mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            if old_mode is not None:
                os.fchmod(stream.fileno(), old_mode)
            stream.write(payload)
            if durable:
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        if durable:
            readable_dir = _openat2(directory_fd, ".", _DIR_FLAGS)
            try:
                os.fsync(readable_dir)
            finally:
                os.close(readable_dir)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _assert_admin_controlled(fd):
    info = os.fstat(fd)
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError("Agent import root is not administrator-controlled")


def _validate_import_tree(directory_fd, depth=0):
    if depth > 128:
        raise ValueError("Agent import tree nesting is too deep")
    for name in os.listdir(directory_fd):
        fd = open_beneath(directory_fd, name, os.O_PATH | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError("Unsafe entry in agent import tree")
            _assert_admin_controlled(fd)
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise ValueError("Hardlinked file in agent import tree")
            if stat.S_ISDIR(info.st_mode):
                with child_directory(directory_fd, name) as child:
                    _validate_import_tree(child, depth + 1)
        finally:
            os.close(fd)


def _trusted_tree(base, components):
    path = Path(base)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Configured base must be an absolute path without '..'")
    with ExitStack() as stack:
        root = os.open("/", _DIR_FLAGS | os.O_NOFOLLOW)
        stack.callback(os.close, root)
        _assert_admin_controlled(root)
        for name in path.parts[1:]:
            _component(name)
            child = os.open(name, _DIR_FLAGS | os.O_NOFOLLOW, dir_fd=root)
            stack.callback(os.close, child)
            root = child
            _assert_admin_controlled(root)
        for name in components:
            try:
                root = stack.enter_context(child_directory(root, name))
            except FileNotFoundError:
                return None
            _assert_admin_controlled(root)
        _validate_import_tree(root)
        return os.dup(root)


def trusted_agent_import_root(base, lang, agent_name):
    """Return an owned FD to a root-controlled agent tree, or None if absent.

    Every ancestor and descendant is verified because Python can import any
    module beneath this directory. The caller must keep the returned FD open
    for the child's lifetime and pass it through exec; using the original
    absolute path would discard the anchor.
    """
    _component(lang)
    _component(agent_name)
    return _trusted_tree(base, ("agents", f"{lang}_core", agent_name))


def trusted_shared_agent_root(base, lang):
    """Return an owned FD to the fully validated shared agent source tree."""
    _component(lang)
    return _trusted_tree(base, ("agents", f"{lang}_core"))


def trusted_shared_core_root(base):
    """Return an owned FD to the fully validated shared core source tree."""
    return _trusted_tree(base, ("core",))
