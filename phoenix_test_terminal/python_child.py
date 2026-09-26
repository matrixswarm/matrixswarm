"""Dedicated startup-policy subprocess adapter; never invokes a shell."""
from pathlib import Path
import sys


def main():
    root, sandbox = (Path(value).resolve() for value in sys.argv[1:])
    if Path.cwd().resolve() != sandbox or not (sandbox / ".phoenix-test-only").is_file():
        raise RuntimeError("Not in a test sandbox")
    sys.path[:0] = [str(root), str(root / "phoenix")]
    from phoenix_test_terminal.safety import install_guards
    install_guards(sandbox)
    payload = sys.stdin.buffer.read(65537)
    if len(payload) > 65536:
        raise ValueError("Test script too large")
    script = payload.decode("utf-8")
    exec(compile(script, "<startup-policy-test>", "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    main()
