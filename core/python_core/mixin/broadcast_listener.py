# BroadcastListenerMixin — watches the /broadcast/ folder and routes to handlers
import os
import time


def update_broadcast_flag(self, session_id=None, remove=False):
    """
    Creates or removes a local filesystem flag.

    This method is used to signal other processes or agents within the
    swarm that a GUI client is actively connected via WebSocket. The
    flag's presence can be used to trigger certain behaviors, such as
    sending real-time alerts.
    """
    base = os.path.join(self.path_resolution["comm_path_resolved"], "broadcast")
    os.makedirs(base, exist_ok=True)

    flag = os.path.join(base, f"connected.flag.{session_id}") if session_id else os.path.join(base, "connected.flag")

    if remove:
        if os.path.exists(flag):
            os.remove(flag)
        return

    open(flag, "w").close()
    os.utime(flag, None)


def _cleanup_old_broadcast_flags(self):
    """
    Remove stale WebSocket broadcast flags from the /broadcast directory.
    This runs once per packet_listener() cycle (via packet_listener_post).
    """
    try:
        broadcast_dir = os.path.join(self.path_resolution["comm_path_resolved"], "broadcast")
        if not os.path.isdir(broadcast_dir):
            return

        now = time.time()
        active = set(self._sessions.keys())
        removed = 0

        for fname in os.listdir(broadcast_dir):
            if not fname.startswith("connected.flag"):
                continue
            fpath = os.path.join(broadcast_dir, fname)

            # Extract session id (if present)
            parts = fname.split(".")
            sid = parts[-1] if len(parts) > 2 else None

            # delete if stale or not in active sessions
            if (sid and sid not in active) or (now - os.path.getmtime(fpath) > 900):
                try:
                    os.remove(fpath)
                    removed += 1
                except Exception:
                    continue

        if removed and self.debug.is_enabled():
            self.log(f"[CLEANUP] Removed {removed} stale broadcast flags from {broadcast_dir}")

    except Exception as e:
        self.log("[CLEANUP][ERROR] Broadcast cleanup failed", error=e)