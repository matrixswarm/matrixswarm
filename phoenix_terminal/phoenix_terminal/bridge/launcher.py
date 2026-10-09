"""Launch Phoenix with a narrow optional Connect/session endpoint."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def launch(phoenix_root: Path, data_dir: Path) -> int:
    """Launch without monkeypatches; Terminal still owns connection approval.

    Phoenix independently checks the approved grant and matching Vault revision
    before listing or opening its ordinary cockpit tabs. No generic GUI RPC.
    """
    phoenix_root = phoenix_root.resolve()
    if not all((phoenix_root / name).exists() for name in ("phoenix.py", "matrix_gui", "README.md")):
        raise ValueError(f"not a recognized Phoenix source directory: {phoenix_root}")

    previous_cwd, previous_argv, previous_path = Path.cwd(), sys.argv, list(sys.path)
    previous_state = os.environ.get("PHOENIX_TERMINAL_DATA_DIR")
    try:
        os.environ["PHOENIX_TERMINAL_DATA_DIR"] = str(data_dir.resolve())
        sys.path.insert(0, str(phoenix_root))
        os.chdir(str(phoenix_root))
        sys.argv = [str(phoenix_root / "phoenix.py")]
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as exc:
            if exc.code is None:
                return 0
            if isinstance(exc.code, int):
                return exc.code
            raise RuntimeError("Phoenix exited with an application error.") from exc
        return 0
    finally:
        os.chdir(previous_cwd)
        sys.argv = previous_argv
        sys.path[:] = previous_path
        if previous_state is None:
            os.environ.pop("PHOENIX_TERMINAL_DATA_DIR", None)
        else:
            os.environ["PHOENIX_TERMINAL_DATA_DIR"] = previous_state
