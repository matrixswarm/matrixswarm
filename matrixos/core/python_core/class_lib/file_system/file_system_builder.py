"""Construct agent filesystem entries beneath an opened directory."""

import json
import os
from contextlib import ExitStack
from pathlib import Path
import stat
import uuid

from core.python_core.safe_paths import _component, child_directory, open_base, open_beneath


class FileSystemBuilder:
    def _write_file(self, parent_fd, name, content, atomic):
        name = _component(name)
        payload = json.dumps(content, indent=4) if isinstance(content, (dict, list)) else str(content or "")
        encoded = payload.encode("utf-8")
        if atomic:
            try:
                existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                    raise ValueError("Unsafe existing file in agent filesystem")
            temporary = f".{name}.{uuid.uuid4().hex}.tmp"
            fd = open_beneath(parent_fd, temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                os.rename(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
        else:
            # Do not truncate until we know this is an ordinary, unshared file.
            fd = open_beneath(parent_fd, name, os.O_WRONLY | os.O_CREAT | os.O_NONBLOCK, 0o666)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Unsafe existing file in agent filesystem")
                os.ftruncate(fd, 0)
                with os.fdopen(fd, "wb") as stream:
                    fd = -1
                    stream.write(encoded)
            finally:
                if fd >= 0:
                    os.close(fd)

    def _process(self, parent_fd, item):
        if not isinstance(item, dict):
            raise ValueError("Invalid agent filesystem entry")
        item_type = item.get("type", "unknown")
        if item_type not in ("d", "f"):
            if not item:  # Historical empty placeholder in Matrix's directive.
                return
            raise ValueError("Invalid agent filesystem entry type")
        name = _component(item.get("name"))
        content = item.get("content")
        if item_type == "d":
            with child_directory(parent_fd, name, create=True) as directory:
                if isinstance(content, dict):
                    for key, value in content.items():
                        self._process(directory, {"name": key, "type": "d" if isinstance(value, dict) else "f", "content": value})
        else:
            self._write_file(parent_fd, name, content, item.get("atomic", False))

    def process_item(self, base, item, current_path=None, create_path=True):
        base_path = Path(base)
        selected = Path(current_path) if current_path is not None else base_path
        try:
            relative = selected.relative_to(base_path)
        except ValueError as exc:
            raise ValueError("Agent filesystem path escapes its root") from exc
        with ExitStack() as stack:
            root_fd = open_base(base_path, create=create_path)
            stack.callback(os.close, root_fd)
            directory = root_fd
            for name in relative.parts:
                directory = stack.enter_context(child_directory(directory, name, create=create_path))
            self._process(directory, item)

    def process_selection(self, base, selection):
        # Keep a single anchored handle for the whole selection.
        with ExitStack() as stack:
            root_fd = open_base(base, create=True)
            stack.callback(os.close, root_fd)
            for item in selection:
                self._process(root_fd, item)

    def process_item_fd(self, directory_fd, item):
        self._process(directory_fd, item)

    def process_selection_fd(self, directory_fd, selection):
        for item in selection:
            self._process(directory_fd, item)
