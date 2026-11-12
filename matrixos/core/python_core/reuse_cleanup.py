"""Safely retire obsolete runtime communication folders during boot reuse."""

import os
import re
from contextlib import ExitStack
from pathlib import Path
import stat
import uuid

from core.python_core.safe_paths import child_directory, open_base, open_beneath


def validate_agent_ids(ids):
    """Require nonempty, distinct, single-component agent identifiers."""
    result = set()
    for value in ids:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid agent identifier in boot directive")
        if value in result:
            raise ValueError("Duplicate agent identifier in boot directive")
        result.add(value)
    if not result:
        raise ValueError("Boot directive contains no agent identifiers")
    return frozenset(result)


def validate_directive_tree(directive):
    """Validate enabled nodes before TreeParser can silently discard them."""
    if not isinstance(directive, dict):
        raise ValueError("Invalid boot directive tree")
    root = directive.get("agent_tree", directive)
    ids = []

    def visit(node):
        if not isinstance(node, dict):
            raise ValueError("Invalid agent in boot directive")
        if node.get("enabled") is False:
            return
        ids.append(node.get("universal_id"))
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Invalid agent children in boot directive")
        for child in children:
            visit(child)

    visit(root)
    return validate_agent_ids(ids)


def require_directory(path, *, missing_ok=False):
    """Reject links and non-directories without following a final symlink."""
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return False
        raise
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"Unsafe directory in reused universe: {path}")
    return True


def validate_reuse_paths(base, universe, boot_id):
    """Check fixed roots before constructing a reuse-mode path manager."""
    validate_agent_ids((universe,))
    validate_agent_ids((boot_id,))
    base = Path(base)
    runtime = base / "universes" / "runtime"
    static = base / "universes" / "static"
    for path in (base / "universes", runtime, runtime / universe,
                 runtime / universe / boot_id, static, static / universe,
                 static / universe / boot_id):
        require_directory(path, missing_ok=True)
    boot = runtime / universe / boot_id
    for path in (boot / "comm", boot / "pod", boot / "retired-agent-comm", boot / "retired-agent-signals"):
        require_directory(path, missing_ok=True)


def _tree_preflight(directory_fd, depth=0):
    if depth > 128:
        raise ValueError("Pod directory nesting is too deep")
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            continue  # links are unlinked, never traversed
        flags = os.O_PATH | os.O_NOFOLLOW
        with ExitStack() as stack:
            child = open_beneath(directory_fd, name, flags)
            stack.callback(os.close, child)
            if stat.S_ISDIR(info.st_mode):
                readable = open_beneath(directory_fd, name)
                stack.callback(os.close, readable)
                _tree_preflight(readable, depth + 1)


def _remove_contents(directory_fd, depth=0):
    if depth > 128:
        raise ValueError("Pod directory nesting is too deep")
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with child_directory(directory_fd, name) as child:
                _remove_contents(child, depth + 1)
            os.rmdir(name, dir_fd=directory_fd)
        else:
            # Check mount boundaries again before unlinking a non-link entry.
            if not stat.S_ISLNK(info.st_mode):
                fd = open_beneath(directory_fd, name, os.O_PATH | os.O_NOFOLLOW)
                os.close(fd)
            os.unlink(name, dir_fd=directory_fd)


def validate_pod_entries(runtime_root, *, root_fd=None):
    """Reject suspicious pod entries before moving any channel data."""
    owned = open_base(runtime_root) if root_fd is None else os.dup(root_fd)
    try:
        try:
            pod_fd = open_beneath(owned, "pod")
        except FileNotFoundError:
            return
        try:
            for name in os.listdir(pod_fd):
                if stat.S_ISLNK(os.stat(name, dir_fd=pod_fd, follow_symlinks=False).st_mode):
                    raise ValueError(f"Unsafe link in reused pod directory: {name}")
            _tree_preflight(pod_fd)
        finally:
            os.close(pod_fd)
    finally:
        os.close(owned)


def clear_pods(runtime_root, *, root_fd=None):
    """Delete pod entries by anchored handles, refusing mounted subtrees."""
    owned = open_base(runtime_root) if root_fd is None else os.dup(root_fd)
    try:
        try:
            pod_fd = open_beneath(owned, "pod")
        except FileNotFoundError:
            return
        try:
            _tree_preflight(pod_fd)
            _remove_contents(pod_fd)
        finally:
            os.close(pod_fd)
    finally:
        os.close(owned)


def retire_active_signals(runtime_root, *, root_fd=None):
    """Move direct control-channel files aside before clearing a reused boot."""
    runtime_root = Path(runtime_root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        root_fd = open_base(runtime_root) if root_fd is None else os.dup(root_fd)
        stack.callback(os.close, root_fd)
        try:
            comm_fd = open_beneath(root_fd, "comm")
        except FileNotFoundError:
            return None
        stack.callback(os.close, comm_fd)
        pending = {}
        for agent in os.listdir(comm_fd):
            validate_agent_ids((agent,))
            agent_fd = open_beneath(comm_fd, agent)
            try:
                for channel in ("incoming", "hello.moto", "spawn", "directive"):
                    try:
                        channel_fd = open_beneath(agent_fd, channel)
                    except FileNotFoundError:
                        continue
                    try:
                        for name in os.listdir(channel_fd):
                            info = os.stat(name, dir_fd=channel_fd, follow_symlinks=False)
                            if stat.S_ISLNK(info.st_mode):
                                raise ValueError(f"Unsafe link in reused agent channel: {agent}/{channel}/{name}")
                            if not stat.S_ISDIR(info.st_mode):
                                entry_fd = open_beneath(channel_fd, name, os.O_PATH | os.O_NOFOLLOW)
                                os.close(entry_fd)
                                pending.setdefault(agent, {}).setdefault(channel, []).append(name)
                    finally:
                        os.close(channel_fd)
            finally:
                os.close(agent_fd)
        try:
            info = os.stat("retired-agent-signals", dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if info is not None and not stat.S_ISDIR(info.st_mode):
            raise ValueError("Unsafe signal retirement directory")
        if not pending:
            return None
        if info is None:
            os.mkdir("retired-agent-signals", mode=0o700, dir_fd=root_fd)
        retired_fd = open_beneath(root_fd, "retired-agent-signals")
        stack.callback(os.close, retired_fd)
        token = uuid.uuid4().hex
        os.mkdir(token, mode=0o700, dir_fd=retired_fd)
        batch_fd = open_beneath(retired_fd, token)
        stack.callback(os.close, batch_fd)
        for agent, channels in pending.items():
            with ExitStack() as agent_stack:
                source_agent_fd = open_beneath(comm_fd, agent)
                agent_stack.callback(os.close, source_agent_fd)
                os.mkdir(agent, mode=0o700, dir_fd=batch_fd)
                target_agent_fd = open_beneath(batch_fd, agent)
                agent_stack.callback(os.close, target_agent_fd)
                for channel, names in channels.items():
                    with ExitStack() as channel_stack:
                        source_fd = open_beneath(source_agent_fd, channel)
                        channel_stack.callback(os.close, source_fd)
                        os.mkdir(channel, mode=0o700, dir_fd=target_agent_fd)
                        target_fd = open_beneath(target_agent_fd, channel)
                        channel_stack.callback(os.close, target_fd)
                        for name in names:
                            info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
                            if stat.S_ISLNK(info.st_mode) or stat.S_ISDIR(info.st_mode):
                                raise ValueError(f"Changed entry in reused agent channel: {agent}/{channel}/{name}")
                            entry_fd = open_beneath(source_fd, name, os.O_PATH | os.O_NOFOLLOW)
                            os.close(entry_fd)
                            os.rename(name, name, src_dir_fd=source_fd, dst_dir_fd=target_fd)
        return runtime_root / "retired-agent-signals" / token


def retire_obsolete_runtime_comm(runtime_root, active_ids, *, root_fd=None):
    """Move obsolete folders aside, keeping their contents recoverable.

    The caller must stop all prior agents and validate the decrypted directive
    before calling. No static or persistent paths are traversed or changed.
    """
    active = validate_agent_ids(active_ids)
    runtime_root = Path(runtime_root)
    if not all(hasattr(os, key) for key in ("O_DIRECTORY", "O_NOFOLLOW")):
        raise RuntimeError("Safe runtime retirement requires POSIX directory descriptors")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        root_fd = open_base(runtime_root) if root_fd is None else os.dup(root_fd)
        stack.callback(os.close, root_fd)
        try:
            comm_fd = open_beneath(root_fd, "comm")
        except FileNotFoundError:
            return None
        stack.callback(os.close, comm_fd)
        try:
            retired_info = os.stat("retired-agent-comm", dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISDIR(retired_info.st_mode):
                raise ValueError("Unsafe retirement directory")
        entries = os.listdir(comm_fd)
        for name in entries:
            validate_agent_ids((name,))
            info = os.stat(name, dir_fd=comm_fd, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"Unsafe entry in reused agent channels: {name}")
            if name not in active:
                with child_directory(comm_fd, name) as obsolete_fd:
                    _tree_preflight(obsolete_fd)
                continue
            agent_fd = open_beneath(comm_fd, name)
            try:
                # Existing cleanup enters these paths; reject links before any move.
                for child in ("incoming", "hello.moto", "spawn", "directive"):
                    try:
                        child_fd = open_beneath(agent_fd, child)
                    except FileNotFoundError:
                        continue
                    try:
                        for item in os.listdir(child_fd):
                            item_info = os.stat(item, dir_fd=child_fd, follow_symlinks=False)
                            if stat.S_ISLNK(item_info.st_mode):
                                raise ValueError(f"Unsafe link in reused agent channel: {name}/{child}/{item}")
                    finally:
                        os.close(child_fd)
            finally:
                os.close(agent_fd)
        obsolete = [name for name in entries if name not in active]
        if not obsolete:
            return None
        try:
            os.mkdir("retired-agent-comm", mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        retired_fd = open_beneath(root_fd, "retired-agent-comm")
        stack.callback(os.close, retired_fd)
        token = uuid.uuid4().hex
        os.mkdir(token, mode=0o700, dir_fd=retired_fd)
        destination_fd = open_beneath(retired_fd, token)
        stack.callback(os.close, destination_fd)
        for name in obsolete:
            os.rename(name, name, src_dir_fd=comm_fd, dst_dir_fd=destination_fd)
        return runtime_root / "retired-agent-comm" / token


def prepare_reused_runtime(base, universe, boot_id, active_ids):
    """Anchor the runtime boot once through preflight, retirement and cleanup."""
    validate_agent_ids((universe,))
    validate_agent_ids((boot_id,))
    runtime_root = Path(base) / "universes" / "runtime" / universe / boot_id
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        universes = stack.enter_context(child_directory(root, "universes", traverse_only=True))
        static = stack.enter_context(child_directory(universes, "static", traverse_only=True))
        static = stack.enter_context(child_directory(static, universe))
        static = stack.enter_context(child_directory(static, boot_id))
        # Hold and validate the static ancestor too; never traverse or remove
        # its agent data while retiring runtime channels.
        for name in ("comm", "pod"):
            try:
                fd = open_beneath(static, name)
            except FileNotFoundError:
                continue
            stack.callback(os.close, fd)
        root = stack.enter_context(child_directory(universes, "runtime", traverse_only=True))
        root = stack.enter_context(child_directory(root, universe))
        root = stack.enter_context(child_directory(root, boot_id))
        validate_pod_entries(runtime_root, root_fd=root)
        retired = retire_obsolete_runtime_comm(runtime_root, active_ids, root_fd=root)
        signals = retire_active_signals(runtime_root, root_fd=root)
        clear_pods(runtime_root, root_fd=root)
        return retired, signals


def purge_runtime_paths(base, universe, boot_id):
    """Implement --clean without following paths or crossing mounts."""
    validate_agent_ids((universe,))
    validate_agent_ids((boot_id,))
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        for name in ("universes", "runtime"):
            root = stack.enter_context(child_directory(root, name, traverse_only=True))
        for name in (universe, boot_id):
            root = stack.enter_context(child_directory(root, name))
        # Inspect both roots before deleting either one.
        existing = []
        for name in ("comm", "pod"):
            try:
                fd = open_beneath(root, name)
            except FileNotFoundError:
                continue
            try:
                _tree_preflight(fd)
            finally:
                os.close(fd)
            existing.append(name)
        for name in existing:
            with child_directory(root, name) as fd:
                _remove_contents(fd)
        # Startup immediately opens these roots through the anchored path
        # helpers. Preserve them after clearing, and restore any absent root.
        for name in ("comm", "pod"):
            with child_directory(root, name, create=True):
                pass


def _plan_universe_cleanup(stack, root, universe, remove_all, preserve_boot=None):
    plans = []
    try:
        universes = stack.enter_context(child_directory(root, "universes", traverse_only=True))
    except FileNotFoundError:
        if preserve_boot is not None and not remove_all:
            raise ValueError("Cannot preserve active boot: universes directory is missing")
        return plans
    for kind in ("runtime", "static"):
        try:
            kind_fd = stack.enter_context(child_directory(universes, kind, traverse_only=True))
            universe_fd = stack.enter_context(child_directory(kind_fd, universe))
        except FileNotFoundError:
            if preserve_boot is not None and not remove_all:
                raise ValueError(f"Cannot preserve active boot: {kind} universe is missing")
            continue
        if remove_all:
            _tree_preflight(universe_fd)
            plans.append((kind, kind_fd, universe_fd, None))
            continue
        protected = set()
        if preserve_boot is not None:
            with child_directory(universe_fd, preserve_boot):
                pass
            protected.add(preserve_boot)
        try:
            latest_info = os.stat("latest", dir_fd=universe_fd, follow_symlinks=False)
        except FileNotFoundError:
            latest_info = None
        if latest_info is not None:
            if not stat.S_ISLNK(latest_info.st_mode):
                raise ValueError(f"Unsafe latest entry in {kind} universe")
            target = os.readlink("latest", dir_fd=universe_fd)
            validate_agent_ids((target,))
            with child_directory(universe_fd, target):
                pass
            protected.add(target)
        boots = []
        for name in os.listdir(universe_fd):
            # Unknown directories may contain user data; only generated boot
            # IDs have a well-defined ordering and are eligible for pruning.
            if not re.fullmatch(r"[0-9]{8}_[0-9]{6}", name):
                continue
            info = os.stat(name, dir_fd=universe_fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                with child_directory(universe_fd, name):
                    pass
                boots.append(name)
        ordered = sorted(boots)
        if ordered:
            if preserve_boot is None:
                raise ValueError("Cannot prune boot directories without an authoritative active boot ID")
            protected.add(ordered[-1])
        for name in ordered:
            if name in protected:
                continue
            with child_directory(universe_fd, name) as boot_fd:
                _tree_preflight(boot_fd)
            plans.append((kind, kind_fd, universe_fd, name))
    return plans


def _execute_universe_cleanup(base, universe, plans):
    removed = []
    for kind, kind_fd, universe_fd, boot_name in plans:
        if boot_name is None:
            _remove_contents(universe_fd)
            os.rmdir(universe, dir_fd=kind_fd)
            removed.append(Path(base) / "universes" / kind / universe)
        else:
            with child_directory(universe_fd, boot_name) as boot_fd:
                _remove_contents(boot_fd)
            os.rmdir(boot_name, dir_fd=universe_fd)
            removed.append(Path(base) / "universes" / kind / universe / boot_name)
    return removed


def cleanup_universe(base, universe, *, remove_all=False, preserve_boot=None):
    """Clean runtime/static trees after preflighting both for unsafe mounts."""
    validate_agent_ids((universe,))
    if preserve_boot is not None:
        validate_agent_ids((preserve_boot,))
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        plans = _plan_universe_cleanup(stack, root, universe, remove_all, preserve_boot)
        return _execute_universe_cleanup(base, universe, plans)


def _plan_directive_cleanup(stack, root, universe):
    try:
        directives = stack.enter_context(child_directory(root, "boot_directives", traverse_only=True))
    except FileNotFoundError:
        return []
    try:
        keys = stack.enter_context(child_directory(directives, "keys", traverse_only=True))
    except FileNotFoundError:
        keys = None
    plans = []
    for parent, name, relative in (
        (directives, f"{universe}.enc.json", Path("boot_directives") / f"{universe}.enc.json"),
        (keys, f"{universe}.key", Path("boot_directives/keys") / f"{universe}.key"),
    ):
        if parent is None:
            continue
        try:
            fd = open_beneath(parent, name, os.O_PATH | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue
        stack.callback(os.close, fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"Unsafe directive or key entry: {relative}")
        plans.append((parent, name, relative, info.st_dev, info.st_ino))
    return plans


def _execute_directive_cleanup(base, plans):
    removed = []
    for parent, name, relative, device, inode in plans:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (device, inode):
            raise ValueError(f"Directive or key changed during cleanup: {relative}")
        os.unlink(name, dir_fd=parent)
        removed.append(Path(base) / relative)
    return removed


def remove_directive_and_key(base, universe):
    """Delete the exact directive and key only after preflighting both."""
    validate_agent_ids((universe,))
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        plans = _plan_directive_cleanup(stack, root, universe)
        return _execute_directive_cleanup(base, plans)


def cleanup_with_directive_and_key(base, universe):
    """Preflight directive, key, runtime and static trees before deleting any."""
    validate_agent_ids((universe,))
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        directives = _plan_directive_cleanup(stack, root, universe)
        universe_trees = _plan_universe_cleanup(stack, root, universe, True)
        removed = _execute_directive_cleanup(base, directives)
        removed.extend(_execute_universe_cleanup(base, universe, universe_trees))
        return removed
