import os, time

def check_heartbeats(comm_root, agent_id, time_delta_timeout=0):
    """
    Scan hello.moto/ for poke.<thread>.<timeout>.<sleep_for>.<wake_due> files.

    Returns a dict of thread statuses:
        {
            "thread_name": {
                "status": "alive" | "sleeping" | "failed",
                "last_seen": <mtime>,
                "timeout": <int>,
                "sleep_for": <int>,
                "wake_due": <int>,
                "delta": <float>
            }
        }

    If any are failed, the dict will reflect it (no more silent None return).
    """
    base = os.path.join(comm_root, agent_id, "hello.moto")
    now = time.time()
    statuses = {}

    try:
        files = [f for f in os.listdir(base) if f.startswith("poke.")]
    except FileNotFoundError:
        return None

    for fname in files:
        parts = fname.split(".")
        if len(parts) < 5:
            continue  # malformed file

        _, thread, timeout, sleep_for, wake_due = parts[:5]

        timeout = int(timeout) if timeout.isdigit() else 0
        sleep_for = int(sleep_for) if sleep_for.isdigit() else 0
        wake_due = int(wake_due) if wake_due.isdigit() else 0

        fpath = os.path.join(base, fname)
        last_seen = os.path.getmtime(fpath)

        # decide status
        if wake_due and now < wake_due:
            status = "sleeping"
            delta = now - wake_due  # negative until wake expires
        else:
            delta = now - last_seen
            # check against both per-thread timeout and global buffer
            fail_cutoff = max(timeout, time_delta_timeout)
            status = "alive" if fail_cutoff == 0 or delta < fail_cutoff else "failed"

        statuses[thread] = {
            "thread": thread,
            "status": status,
            "last_seen": last_seen,
            "timeout": timeout,
            "sleep_for": sleep_for,
            "wake_due": wake_due,
            "delta": delta,
        }

    return statuses
