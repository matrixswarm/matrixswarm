"""Run the same bounded storage helper locally or over pinned SSH."""
import base64
import json
from pathlib import Path
import subprocess
import sys


def storage_operation(request, transport=None):
    helper = Path(__file__).with_name("snapshot_verifier.py")
    encoded = json.dumps(request).encode("utf-8")
    timeout = int(request.get("limits", {}).get("timeout_sec", 3600)) + 30
    if transport is None:
        result = subprocess.run([sys.executable, "-B", str(helper)], input=encoded,
                                capture_output=True, timeout=timeout, check=False)
    else:
        # Source and JSON travel through private stdin, never shell interpolation.
        source = base64.b64encode(helper.read_bytes()).decode("ascii")
        payload = base64.b64encode(encoded).decode("ascii")
        script = ("python3 - <<'RSYNC_BOY_HELPER'\nimport base64, io, sys\n"
                  f"sys.stdin = io.TextIOWrapper(io.BytesIO(base64.b64decode('{payload}')))\n"
                  f"exec(compile(base64.b64decode('{source}'), '<rsync-boy-storage>', 'exec'), "
                  "{'__name__': '__main__'})\nRSYNC_BOY_HELPER\n").encode("ascii")
        result = transport.run_script(script, check=False, timeout=timeout)
    if len(result.stdout or b"") > 16384:
        raise RuntimeError("Oversized storage helper response")
    try:
        document = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Storage helper returned no valid result") from exc
    if not isinstance(document, dict):
        raise RuntimeError("Storage helper returned invalid result")
    if result.returncode:
        raise RuntimeError("Storage helper failed: " + str(document.get("error_code", "unavailable")))
    return document
