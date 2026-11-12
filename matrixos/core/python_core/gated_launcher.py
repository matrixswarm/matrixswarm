"""Run a child only after its parent has published its boot record."""
import json
import os
import sys


def main():
    try:
        # EOF means that the spawning process failed or died before commit.
        if os.read(0, 1) != b"1":
            return 1
        command = json.loads(os.environ.pop("MATRIX_GATED_COMMAND"))
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            return 1
        os.execvpe(command[0], command, os.environ)
    except (OSError, ValueError, KeyError, TypeError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
