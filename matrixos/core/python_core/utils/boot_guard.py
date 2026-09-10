import os
import re
import psutil

def validate_universe_id(uid):
    pattern = r"^[a-zA-Z0-9_-]{1,32}$"
    if not re.match(pattern, uid):
        print(f"[BLOCKED] Invalid universe ID: '{uid}'")
        os._exit(1)

def enforce_single_matrix_instance(universe_id):
    # Matrix now has a generated universal ID, so the universe prefix is the
    # stable singleton boundary.  Any surviving agent means this universe is
    # still active and a second root must not be launched over it.
    label = f"--job {universe_id}:"
    for proc in psutil.process_iter(['cmdline']):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if label in cmdline:
                print(f"[BLOCKED] Matrix already running in '{universe_id}'.")
                os._exit(1)
        except Exception:
            continue
