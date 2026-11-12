#!/usr/bin/env python3
"""Publish one existing MatrixOS agent source through a root-only channel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.python_core.safe_paths import open_base, child_directory, open_beneath, write_file_at, trusted_shared_agent_root

MAX_SOURCE_BYTES = 4 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def publish_source(agent_name, expected_hash, stream, *, base="/matrix", _owner_uid=0, _python_exec=None):
    if os.geteuid() != _owner_uid:
        raise PermissionError("Source publication requires the administrator account")
    if not isinstance(agent_name, str) or not _NAME.fullmatch(agent_name):
        raise ValueError("Invalid agent source name")
    if not isinstance(expected_hash, str) or not _HASH.fullmatch(expected_hash):
        raise ValueError("Invalid source SHA-256")
    source = stream.read(MAX_SOURCE_BYTES + 1)
    if not isinstance(source, bytes) or not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError("Source must be between 1 byte and 4 MiB")
    digest = hashlib.sha256(source).hexdigest()
    if digest != expected_hash:
        raise ValueError("Source SHA-256 mismatch")
    # Check syntax with the actual target interpreter, never execute source.
    source.decode("utf-8")
    python_exec = _python_exec or str(Path(base) / ".venv/bin/python3")
    result = subprocess.run([python_exec, "-I", "-S", "-c",
                             "import sys; compile(sys.stdin.buffer.read(), '<agent>', 'exec')"],
                            input=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=20, check=False)
    if result.returncode:
        raise ValueError("Source is invalid for the target Python interpreter")

    trusted = trusted_shared_agent_root(base, "python")
    if trusted is None:
        raise RuntimeError("Administrator-controlled agent source tree is missing")
    os.close(trusted)
    with ExitStack() as stack:
        root = open_base(base)
        stack.callback(os.close, root)
        for part in ("agents", "python_core", agent_name):
            root = stack.enter_context(child_directory(root, part))
        name = agent_name + ".py"
        source_fd = open_beneath(root, name, os.O_RDONLY | os.O_NONBLOCK)
        stack.callback(os.close, source_fd)
        info = os.fstat(source_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != _owner_uid or info.st_mode & 0o022):
            raise ValueError("Existing source is not an administrator-controlled ordinary file")
        write_file_at(root, name, source, durable=True)
    return {"status": "success", "agent": agent_name, "sha256": digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    try:
        result = publish_source(args.agent, args.sha256, sys.stdin.buffer)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
