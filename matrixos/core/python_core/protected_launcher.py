"""Launch one verified agent after applying the Linux non-dumpable boundary."""

import ctypes
import os
import runpy
import sys


PR_SET_DUMPABLE = 4
RUN_PATH_ENV = "MATRIX_AGENT_RUN_PATH"


def _protect_process_memory():
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Root-only agent memory protection requires Linux prctl")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, "PR_SET_DUMPABLE failed")


def main():
    # Apply the boundary before reading or decrypting any agent boot material.
    _protect_process_memory()
    agent_path = os.environ.pop(RUN_PATH_ENV, "")
    if not agent_path or not os.path.isfile(agent_path):
        raise RuntimeError("Protected agent run path is missing or invalid")

    agent_args = sys.argv[1:]
    sys.argv = [agent_path, *agent_args]
    runpy.run_path(agent_path, run_name="__main__")


if __name__ == "__main__":
    main()
