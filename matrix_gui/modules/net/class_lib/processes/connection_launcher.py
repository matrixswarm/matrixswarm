# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import importlib
import threading
import copy

import time
import uuid
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.net.connector.interfaces.connector_spec import ConnectorSpec, ConnectorPolicy

class ConnectionLauncher:
    """
    ConnectionLauncher — Swarm Thread Orchestrator
    ------------------------------------------
    • Dynamically loads classes
    • Executes them as managed threads
    • Supports ephemeral and persistent workers
    • Centralized logging via BootAgent.log
    """
    def __init__(self):
        """
        Initialize the ConnectionLauncher with empty registries and lock.

        Attributes:
            _threads (dict): Maps thread_id → threading.Thread instance.
            _registry (dict): Maps universal_id → metadata dict for each connector.
            _shared_state (dict): Maps universal_id → shared context dict.
            _lock (threading.Lock): Ensures thread-safe registry updates.
        """
        self._threads = {}        # thread_id -> Thread
        self._registry = {}       # uid -> ConnectorSpec
        self._shared_state = {}   # uid -> shared dict
        self._lock = threading.Lock()

        print("ConnectionLauncher initialized")

    # --------------------------------------------------
    def load_spec(self, spec: ConnectorSpec, check_interval=30):
        """
        Register a connector spec under its universal_id (uid).
        Spec contains class_path + policy + context.
        """
        with self._lock:
            self._registry[spec.uid] = spec

            self._shared_state[spec.uid] = {
                "universal_id": spec.uid,
                "thread_id": None,
                "class_path": spec.class_path,
                "context": spec.context,
                "started_at": None,
                "last_heartbeat": None,
                "stop": False,
                "reboot_now": False,
            }

            # optional per-spec config
            spec.context.setdefault("check_interval", check_interval)

        return self

    def update_policy(self, uid: str, **patch):
        """
        Patch policy fields for a connector without needing it instantiated.
        Example: update_policy(uid, monitor=True, auto_start=False, ready=True)
        """
        with self._lock:
            spec = self._registry.get(uid)
            if not spec:
                return False

            for k, v in patch.items():
                if hasattr(spec.policy, k):
                    setattr(spec.policy, k, v)
            return True

    def launch(self, uid: str, packet=None, fire_catapult=False):
        """
        Start a connector thread if policy allows.
        - No instantiation is required to evaluate policy gates.
        """
        try:
            with self._lock:
                spec: ConnectorSpec = self._registry.get(uid)
                if not spec:
                    print(f"[LAUNCH][ERROR] No such uid {uid}")
                    return None

                pol = spec.policy
                shared = self._shared_state.get(uid)
                if not shared:
                    print(f"[LAUNCH][ERROR] Missing shared_state for {uid}")
                    return None

                # ---- policy gates (no connector instance required) ----
                if not pol.ready:
                    print(f"[LAUNCH][SKIP] {uid}: not ready ({pol.reason})")
                    return None

                if pol.requires_packet and packet is None:
                    print(f"[LAUNCH][SKIP] {uid}: requires packet ({pol.reason})")
                    return None

                tid = spec.thread_id
                existing = self._threads.get(tid) if tid else None

                if pol.monitor and existing and existing.is_alive():
                    print(
                        f"[LAUNCH][SKIP] {uid}: persistent connector "
                        f"already alive thread={tid}"
                    )
                    return existing

                if not fire_catapult and not pol.auto_start:
                    return None

                # ---- establish runtime shared context ----
                context = spec.context or {}

                # Persistent connectors share their registered control state.
                # Every one-shot SMTP/HTTPS launch receives an isolated state dict,
                # preventing a later launch from overwriting its packet.
                if pol.monitor:
                    runtime_shared = shared
                else:
                    runtime_shared = dict(shared)

                runtime_shared.update({
                    "session_id": context.get("session_id"),
                    "agent": context.get("agent"),
                    "deployment": context.get("deployment"),
                    "context": context,
                    "packet": packet,
                })

                thread_id = uuid.uuid4().hex
                runtime_shared["thread_id"] = thread_id
                runtime_shared["started_at"] = time.time()
                runtime_shared["last_heartbeat"] = time.time()
                runtime_shared["reboot_now"] = False
                runtime_shared["stop"] = False

                # Only persistent/monitored connectors own canonical runtime state.
                if pol.monitor:
                    spec.thread_id = thread_id

                class_path = spec.class_path

            # ---- instantiate AFTER gates pass ----
            cls = self._load_class(class_path)
            instance = cls(shared=runtime_shared)

            t = threading.Thread(
                target=instance.run,
                name=f"thread:{class_path}",
                daemon=True,
            )

            # Only register threads in monitor list if policy.monitor True
            if pol.monitor:
                with self._lock:
                    self._threads[thread_id] = t

            t.start()
            print(f"[ConnectionLauncher][LAUNCH] Started {uid} thread={thread_id} monitor={pol.monitor}")
            return t

        except Exception as e:
            emit_gui_exception_log("ConnectionLauncher.launch()", e)
            return None

    # --------------------------------------------------
    def kill_thread(self, uid: str):
        """
        Stop and detach a managed connector thread.

        Important:
          - Never join while holding the launcher lock.
          - Never reacquire the same non-reentrant lock inside itself.
          - Keep the spec registered so it can be relaunched.
        """
        with self._lock:
            spec = self._registry.get(uid)
            if not spec or not spec.thread_id:
                print(f"[NUKER] No active thread_id to nuke using {uid}.")
                return

            tid = spec.thread_id
            t = self._threads.get(tid)

            shared = self._shared_state.get(uid)
            if shared:
                shared["stop"] = True

        # Join outside the lock so the thread can finish without blocking launcher state.
        if t and t.is_alive():
            print(f"[NUKER] Nuking thread {tid}")
            t.join(timeout=1)
        else:
            print(f"[NUKER] Thread {tid} already dead; cleaning registry.")

        # Cleanup after join, with a fresh lock acquisition.
        with self._lock:
            self._threads.pop(tid, None)

            spec = self._registry.get(uid)
            if spec:
                spec.thread_id = None

            shared = self._shared_state.get(uid)
            if shared:
                # Keep stop=True after explicit kill.
                # launch() will reset it to False when intentionally restarted.
                shared["thread_id"] = None

   # --------------------------------------------------
    def start_monitor(self, check_interval: int = 10):
        if hasattr(self, "_monitor_thread") and self._monitor_thread.is_alive():
            return

        def _monitor_loop():
            print("[ConnectionLauncher][MONITOR] Auto-monitor active.")
            while True:
                try:
                    restarts = []

                    with self._lock:
                        for uid, spec in self._registry.items():
                            pol = spec.policy
                            if not pol.monitor:
                                continue

                            tid = spec.thread_id
                            t = self._threads.get(tid) if tid else None
                            shared = self._shared_state.get(uid) or {}
                            alive = t.is_alive() if t else False

                            if (not alive) and (not bool(shared.get("stop"))):
                                restarts.append(uid)

                            if bool(shared.get("reboot_now")):
                                restarts.append(uid)

                    for uid in set(restarts):
                        print(f"[MONITOR] Restarting {uid}")
                        self.kill_thread(uid)
                        self.launch(uid, fire_catapult=True)

                    time.sleep(check_interval)

                except Exception as e:
                    emit_gui_exception_log("ConnectionLauncher.auto_monitor()", e)
                    time.sleep(check_interval)

        self._monitor_thread = threading.Thread(
            target=_monitor_loop,
            name="thread_launcher_monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    # --------------------------------------------------
    def stop_uid(self, universal_id):
        """
        Signal a registered connector to stop by UID.

        _registry stores ConnectorSpec objects, not metadata dicts, so runtime
        fields must be read as attributes. Keep a dict fallback for older
        registry entries that may still exist during migration/testing.
        """
        with self._lock:
            spec = self._registry.get(universal_id)
            if not spec:
                print(f"[STOP] No such universal_id {universal_id}")
                return False

            shared = self._shared_state.get(universal_id)

            # Mark stop first so the monitor will not immediately restart it.
            if shared:
                shared["stop"] = True

            # retrieve the thread_id from the ConnectorSpec, with legacy dict fallback
            if isinstance(spec, dict):
                tid = spec.get("thread_id")
            else:
                tid = getattr(spec, "thread_id", None)

            # Shared state is also updated by launch(); use it as a fallback.
            if not tid and shared:
                tid = shared.get("thread_id")

            if not tid:
                print(f"[STOP] No active thread for {universal_id}; stop flag set")
                return False

            print(f"[STOP] Signal sent to {universal_id} → thread {tid}")
            return True

    # --------------------------------------------------
    def _load_class(self, dotted_path: str):
        """
        Dynamically import and return a class by its dotted module path.

        Args:
            dotted_path (str): Module and class name, e.g. 'module.sub.ClassName'.

        Returns:
            type: The class object referenced by dotted_path.

        Raises:
            Exception: Propagates any error during import or attribute lookup.
        """
        try:

            module_path, class_name = dotted_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)

            return cls

        except Exception as e:
            emit_gui_exception_log("ConnectionLauncher._load_class()", e)
            raise

    # --------------------------------------------------
    def destroy_all(self, force=False):
        """
        Destroy all active connections and threads managed by the launcher.

        Args:
            force (bool, optional): If True, forcibly clears registries even if
                threads fail to exit gracefully.

        Behavior:
            1. Signals all threads to stop via shared state.
            2. Attempts graceful join on each thread.
            3. Force-cleans thread registry and state maps.
            4. Stops the monitor loop if running.
        """
        try:
            print("[ConnectionLauncher][DESTROY] Commencing full shutdown sequence...")
            with self._lock:
                # signal stop
                for tid, shared in list(self._shared_state.items()):
                    if shared:
                        shared["stop"] = True

                threads = list(self._threads.items())

            # attempt graceful join
            for tid, t in threads:
                if t.is_alive():
                    print(f"[DESTROY] Waiting for thread {tid} to stop...")
                    t.join(timeout=2)

            # final cleanup
            with self._lock:
                self._threads.clear()
                self._registry.clear()
                self._shared_state.clear()

            # stop monitor loop if any
            if hasattr(self, "_monitor_thread") and self._monitor_thread.is_alive():
                print("[DESTROY] Stopping monitor thread...")
                self._monitor_thread = None  # daemon thread will exit on its own

            print("[ConnectionLauncher][DESTROY] ✅ All connections destroyed.")
        except Exception as e:
            if not force:
                emit_gui_exception_log("ConnectionLauncher.destroy_all()", e)
            else:
                # fallback: hard purge everything
                self._threads.clear()
                self._registry.clear()
                self._shared_state.clear()
                self._monitor_thread = None
                print("[ConnectionLauncher][DESTROY][FORCE] ⚠️ Forced purge completed.")


