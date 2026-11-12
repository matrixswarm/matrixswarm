"""Cross-process lifecycle coordination for one MatrixOS universe.

The lock inode is provisioned by an administrator in a directory the swarm
account cannot modify.  Never replace or unlink it: flock follows the inode.
State is updated in place under the exclusive lock; an interrupted or malformed
write is intentionally rejected on the next operation.
"""
import fcntl
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

GENERATION_ENV = "MATRIX_LIFECYCLE_GENERATION"
_UNIVERSE = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
_GENERATION = re.compile(r"[0-9a-f]{32}\Z")
_BOOT_ID = re.compile(r"[0-9_]{1,64}\Z")
_STATES = {"STOPPED", "STARTING", "ACTIVE", "STOPPING"}


class LifecycleError(RuntimeError):
    pass


class LifecycleFence:
    def __init__(self, base, universe, *, _owner_uid=0):
        if not isinstance(universe, str) or not _UNIVERSE.fullmatch(universe):
            raise LifecycleError("Invalid universe for lifecycle fence")
        self.directory = Path(base) / "universes" / "lifecycle" / universe
        self.owner_uid = _owner_uid
        self.fd = None

    def _open(self):
        if self.fd is not None:
            raise LifecycleError("Lifecycle fence is already held")
        if not hasattr(os, "O_PATH"):
            raise LifecycleError("Lifecycle fencing requires Linux O_PATH")
        # Administrative ancestors are traversal-only (0711); opening them
        # for directory reads would deny the unprivileged swarm account.
        flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        # Walk from / using descriptors: O_NOFOLLOW on a full path protects
        # only its final component, not intermediate symlink replacements.
        parts = Path(os.path.abspath(self.directory)).parts
        directory_fd = os.open(parts[0], flags)
        try:
            root_info = os.fstat(directory_fd)
            if root_info.st_uid != 0 or root_info.st_mode & 0o022:
                raise LifecycleError("Lifecycle filesystem root is not administrator controlled")
            for index, part in enumerate(parts[1:], 1):
                next_fd = os.open(part, flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
                # The configured base and its three lifecycle descendants
                # must be controlled by the same administrator. Otherwise
                # an account could replace an ancestor and split flock domains.
                # Production requires the full path chain from / to be
                # administrator controlled; a writable ancestor could swap
                # an entire valid-looking lifecycle root. The private owner
                # override supports unprivileged temporary test fixtures.
                if self.owner_uid == 0 or index >= len(parts) - 4:
                    info = os.fstat(directory_fd)
                    owner = 0 if self.owner_uid == 0 else self.owner_uid
                    if info.st_uid != owner or info.st_mode & 0o022:
                        raise LifecycleError("Lifecycle path is not administrator controlled")
            directory = os.fstat(directory_fd)
            if directory.st_uid != self.owner_uid or directory.st_mode & 0o022:
                raise LifecycleError("Lifecycle directory is not administrator controlled")
            fd = os.open("lock", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid
                        or info.st_gid != directory.st_gid or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) != 0o660):
                    raise LifecycleError("Unsafe lifecycle lock file")
            except BaseException:
                os.close(fd)
                raise
            return fd
        finally:
            os.close(directory_fd)

    def read_state(self):
        if self.fd is None:
            raise LifecycleError("Lifecycle lock is not held")
        os.lseek(self.fd, 0, os.SEEK_SET)
        raw = os.read(self.fd, 4097)
        if len(raw) > 4096:
            raise LifecycleError("Malformed lifecycle state")
        try:
            state = json.loads(raw)
            if (not isinstance(state, dict) or set(state) != {"version", "state", "generation", "boot_id"}
                    or state["version"] != 1 or state["state"] not in _STATES
                    or (state["generation"] is not None and
                        (not isinstance(state["generation"], str) or not _GENERATION.fullmatch(state["generation"])))
                    or (state["state"] != "STOPPED" and state["generation"] is None)
                    or (state["boot_id"] is not None and (not isinstance(state["boot_id"], str)
                        or not _BOOT_ID.fullmatch(state["boot_id"])))
                    or (state["state"] == "ACTIVE" and state["boot_id"] is None)):
                raise ValueError("Invalid state")
            return state
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            raise LifecycleError("Malformed lifecycle state; administrator recovery required") from exc

    def write_state(self, state, generation, boot_id=None):
        if self.fd is None or not getattr(self, "_exclusive", False):
            raise LifecycleError("Exclusive lifecycle lock required")
        if state not in _STATES or (generation is not None and
                (not isinstance(generation, str) or not _GENERATION.fullmatch(generation))) or (state != "STOPPED" and generation is None) or (boot_id is not None and (not isinstance(boot_id, str) or not _BOOT_ID.fullmatch(boot_id))) or (state == "ACTIVE" and boot_id is None):
            raise LifecycleError("Invalid lifecycle state")
        data = json.dumps({"version": 1, "state": state, "generation": generation, "boot_id": boot_id}, separators=(",", ":")).encode()
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        written = 0
        while written < len(data):
            count = os.write(self.fd, data[written:])
            if count <= 0:
                raise LifecycleError("Failed to persist lifecycle state")
            written += count
        os.fsync(self.fd)

    def _validate_active(self, expected):
        if not isinstance(expected, str) or not _GENERATION.fullmatch(expected):
            raise LifecycleError("Missing or invalid agent lifecycle generation")
        state = self.read_state()
        if state["state"] != "ACTIVE" or state["generation"] != expected:
            raise LifecycleError("Stale or inactive universe generation")

    @contextmanager
    def exclusive(self, expected_generation=None):
        fd = self._open()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.fd, self._exclusive = fd, True
            if expected_generation is not None:
                self._validate_active(expected_generation)
            yield self
        finally:
            self.fd, self._exclusive = None, False
            os.close(fd)

    @contextmanager
    def shared(self, expected_generation):
        fd = self._open()
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LifecycleError("Universe lifecycle operation is in progress") from exc
            self.fd, self._exclusive = fd, False
            self._validate_active(expected_generation)
            yield self
        finally:
            self.fd, self._exclusive = None, False
            os.close(fd)
