# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import importlib
import threading

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
        self._instances = {}      # thread_id -> connector instance
        self._registry = {}       # uid -> ConnectorSpec
        self._shared_state = {}   # uid -> shared dict
        self._starting = set()    # persistent UIDs currently being instantiated
        self._lock = threading.Lock()
        self._monitor_stop = threading.Event()
        self._monitor_thread = None

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
        thread_id = None
        persistent = False
        supervised = False
        instance = None
        t = None

        try:
            with self._lock:
                spec: ConnectorSpec = self._registry.get(uid)
                if not spec:
                    print(f"[LAUNCH][ERROR] No such uid {uid}")
                    return None

                pol = spec.policy
                persistent = not bool(pol.requires_packet)
                supervised = bool(pol.monitor)
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

                if not fire_catapult and not pol.auto_start:
                    return None

                existing_tid = getattr(spec, "thread_id", None)
                existing_thread = (
                    self._threads.get(existing_tid)
                    if existing_tid else None
                )

                # Persistent connectors are singletons per launcher/UID. The
                # reservation closes the constructor/start publication race.
                if persistent and existing_thread and existing_thread.is_alive():
                    print(
                        f"[LAUNCH][SKIP] {uid}: already active "
                        f"thread={existing_tid}"
                    )
                    return existing_thread

                if persistent and uid in self._starting:
                    print(f"[LAUNCH][SKIP] {uid}: launch already in progress")
                    return None

                if persistent and existing_tid:
                    self._threads.pop(existing_tid, None)
                    self._instances.pop(existing_tid, None)
                    spec.thread_id = None
                    if shared.get("thread_id") == existing_tid:
                        shared["thread_id"] = None

                # ---- establish runtime context ----
                context = spec.context or {}
                # Ephemeral sends must never overwrite the persistent/shared
                # packet slot.  Each send receives a private state dictionary.
                runtime_shared = shared if persistent else dict(shared)
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

                if persistent:
                    spec.thread_id = thread_id
                    shared["thread_id"] = thread_id
                    self._starting.add(uid)

                class_path = spec.class_path

            # ---- instantiate AFTER gates pass ----
            cls = self._load_class(class_path)
            instance = cls(shared=runtime_shared)

            t = threading.Thread(
                target=instance.run,
                name=f"thread:{class_path}",
                daemon=True,
            )

            # Publish persistent ownership and start atomically so the monitor
            # cannot observe or restart a half-created worker.
            if persistent:
                with self._lock:
                    current_spec = self._registry.get(uid)
                    current_shared = self._shared_state.get(uid)
                    launch_cancelled = (
                        not current_spec
                        or current_spec.thread_id != thread_id
                        or not current_shared
                        or current_shared.get("thread_id") != thread_id
                        or bool(current_shared.get("stop"))
                    )
                    if launch_cancelled:
                        self._starting.discard(uid)
                        if current_spec and current_spec.thread_id == thread_id:
                            current_spec.thread_id = None
                        if (
                            current_shared
                            and current_shared.get("thread_id") == thread_id
                        ):
                            current_shared["thread_id"] = None
                        try:
                            instance.stop()
                            instance.close()
                        except Exception:
                            pass
                        return None

                    self._threads[thread_id] = t
                    self._instances[thread_id] = instance
                    try:
                        t.start()
                        self._starting.discard(uid)
                    except Exception:
                        self._starting.discard(uid)
                        self._threads.pop(thread_id, None)
                        self._instances.pop(thread_id, None)
                        if spec.thread_id == thread_id:
                            spec.thread_id = None
                        if shared.get("thread_id") == thread_id:
                            shared["thread_id"] = None
                        raise
            else:
                t.start()

            print(
                f"[ConnectionLauncher][LAUNCH] Started {uid} "
                f"thread={thread_id} monitor={supervised}"
            )
            return t

        except Exception as e:
            if persistent and thread_id:
                with self._lock:
                    self._starting.discard(uid)
                    if self._threads.get(thread_id) is t:
                        self._threads.pop(thread_id, None)
                    if self._instances.get(thread_id) is instance:
                        self._instances.pop(thread_id, None)

                    current_spec = self._registry.get(uid)
                    if current_spec and current_spec.thread_id == thread_id:
                        current_spec.thread_id = None

                    current_shared = self._shared_state.get(uid)
                    if (
                        current_shared
                        and current_shared.get("thread_id") == thread_id
                    ):
                        current_shared["thread_id"] = None

            if instance and (not t or not t.is_alive()):
                try:
                    instance.close()
                except Exception:
                    pass
            emit_gui_exception_log("ConnectionLauncher.launch()", e)
            return None

    # --------------------------------------------------
    def kill_thread(self, uid: str) -> bool:
        """
        Stop and detach a managed connector thread.

        Returns:
            True when no managed worker remains alive.
            False when the worker survives the join timeout.

        Important:
          - Never join while holding the launcher lock.
          - Retain ownership records while a worker remains alive.
          - Keep the spec registered so it can be relaunched.
        """
        with self._lock:
            spec = self._registry.get(uid)
            if not spec or not spec.thread_id:
                print(f"[NUKER] No active thread_id to nuke using {uid}.")
                return True

            tid = spec.thread_id
            t = self._threads.get(tid)
            instance = self._instances.get(tid)

            shared = self._shared_state.get(uid)
            if shared:
                shared["stop"] = True

        # Wake blocking recv()/poll() calls before waiting. BaseConnector.run()
        # may safely invoke close() again in its own finally block.
        if instance:
            try:
                instance.stop()
            except Exception as e:
                emit_gui_exception_log(
                    f"ConnectionLauncher.kill_thread.stop:{uid}", e
                )
            try:
                instance.close()
            except Exception as e:
                emit_gui_exception_log(
                    f"ConnectionLauncher.kill_thread.close:{uid}", e
                )

        # Join outside the lock so the worker can finish normally.
        if t and t.is_alive():
            print(f"[NUKER] Nuking thread {tid}")
            t.join(timeout=2)
            if t.is_alive():
                print(
                    f"[NUKER][TIMEOUT] Thread {tid} for {uid} is still alive; "
                    "retaining launcher ownership."
                )
                return False
        else:
            print(f"[NUKER] Thread {tid} already dead; cleaning registry.")

        # Clear only records that still belong to the worker just stopped.
        with self._lock:
            if self._threads.get(tid) is t:
                self._threads.pop(tid, None)
            if self._instances.get(tid) is instance:
                self._instances.pop(tid, None)

            spec = self._registry.get(uid)
            if spec and spec.thread_id == tid:
                spec.thread_id = None

            shared = self._shared_state.get(uid)
            if shared and shared.get("thread_id") == tid:
                # Keep stop=True after explicit kill.
                # launch() will reset it to False when intentionally restarted.
                shared["thread_id"] = None

        return True

    # --------------------------------------------------
    def start_monitor(self, check_interval: int = 10):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._monitor_stop.clear()

        def _monitor_loop():
            print("[ConnectionLauncher][MONITOR] Auto-monitor active.")
            while not self._monitor_stop.is_set():
                try:
                    restarts = []

                    with self._lock:
                        for uid, spec in self._registry.items():
                            pol = spec.policy
                            if not pol.monitor:
                                continue

                            if uid in self._starting:
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
                        if self._monitor_stop.is_set():
                            break
                        print(f"[MONITOR] Restarting {uid}")
                        if not self.kill_thread(uid):
                            print(
                                f"[MONITOR] Restart deferred for {uid}: "
                                "existing thread is still alive."
                            )
                            continue
                        self.launch(uid, fire_catapult=True)

                    if self._monitor_stop.wait(check_interval):
                        break

                except Exception as e:
                    emit_gui_exception_log("ConnectionLauncher.auto_monitor()", e)
                    if self._monitor_stop.wait(check_interval):
                        break

            print("[ConnectionLauncher][MONITOR] Auto-monitor stopped.")

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
    def destroy_all(self, force=False) -> bool:
        """
        Destroy all active connections and threads managed by the launcher.

        Args:
            force (bool, optional): If True, forcibly clears registries even if
                threads fail to exit gracefully.

        Behavior:
            1. Stops the monitor and blocks automatic restarts.
            2. Signals connectors and interrupts blocking I/O.
            3. Joins managed workers.
            4. Retains ownership of survivors unless force=True.
        """
        try:
            print("[ConnectionLauncher][DESTROY] Commencing full shutdown sequence...")
            self._monitor_stop.set()
            monitor_thread = self._monitor_thread

            if (
                monitor_thread
                and monitor_thread.is_alive()
                and monitor_thread is not threading.current_thread()
            ):
                print("[DESTROY] Stopping monitor thread...")
                monitor_thread.join(timeout=2)

            with self._lock:
                for shared in self._shared_state.values():
                    if shared:
                        shared["stop"] = True

            # Give in-progress constructors a bounded chance to observe the
            # stop flag and cancel before the ownership snapshot.
            start_deadline = time.monotonic() + 2
            while True:
                with self._lock:
                    pending_starts = set(self._starting)
                if not pending_starts or time.monotonic() >= start_deadline:
                    break
                time.sleep(0.01)

            with self._lock:
                pending_starts = set(self._starting)
                pending_tids = {
                    getattr(self._registry.get(uid), "thread_id", None)
                    for uid in pending_starts
                }
                pending_tids.discard(None)

                tids = (
                    set(self._threads)
                    | set(self._instances)
                    | {
                        spec.thread_id
                        for spec in self._registry.values()
                        if getattr(spec, "thread_id", None)
                    }
                )
                workers = [
                    (
                        tid,
                        self._threads.get(tid),
                        self._instances.get(tid),
                    )
                    for tid in tids
                ]

            for tid, _, instance in workers:
                if not instance:
                    continue
                try:
                    instance.stop()
                except Exception as e:
                    emit_gui_exception_log(
                        f"ConnectionLauncher.destroy_all.stop:{tid}", e
                    )
                try:
                    instance.close()
                except Exception as e:
                    emit_gui_exception_log(
                        f"ConnectionLauncher.destroy_all.close:{tid}", e
                    )

            for tid, t, _ in workers:
                if t and t.is_alive():
                    print(f"[DESTROY] Waiting for thread {tid} to stop...")
                    t.join(timeout=2)

            survivors = {
                tid for tid, t, _ in workers
                if t and t.is_alive()
            }
            monitor_survived = bool(
                monitor_thread
                and monitor_thread.is_alive()
                and monitor_thread is not threading.current_thread()
            )
            incomplete = bool(
                survivors or pending_starts or monitor_survived
            )

            if incomplete and not force:
                dead_tids = (
                    {tid for tid, _, _ in workers}
                    - survivors
                    - pending_tids
                )
                with self._lock:
                    for tid in dead_tids:
                        self._threads.pop(tid, None)
                        self._instances.pop(tid, None)

                    for uid, spec in self._registry.items():
                        tid = getattr(spec, "thread_id", None)
                        if tid in dead_tids:
                            spec.thread_id = None
                            shared = self._shared_state.get(uid)
                            if shared and shared.get("thread_id") == tid:
                                shared["thread_id"] = None

                if monitor_thread and not monitor_thread.is_alive():
                    self._monitor_thread = None

                print(
                    "[ConnectionLauncher][DESTROY][INCOMPLETE] "
                    f"workers={len(survivors)} "
                    f"starting={len(pending_starts)} "
                    f"monitor_alive={monitor_survived}; ownership retained."
                )
                return False

            with self._lock:
                self._threads.clear()
                self._instances.clear()
                self._starting.clear()
                self._registry.clear()
                self._shared_state.clear()

            self._monitor_thread = None

            if incomplete:
                print(
                    "[ConnectionLauncher][DESTROY][FORCE] Purged ownership "
                    "while managed activity was still present."
                )
                return False

            print("[ConnectionLauncher][DESTROY] ✅ All connections destroyed.")
            return True
        except Exception as e:
            if not force:
                emit_gui_exception_log("ConnectionLauncher.destroy_all()", e)
                return False
            else:
                self._monitor_stop.set()
                with self._lock:
                    self._threads.clear()
                    self._instances.clear()
                    self._starting.clear()
                    self._registry.clear()
                    self._shared_state.clear()
                self._monitor_thread = None
                print("[ConnectionLauncher][DESTROY][FORCE] ⚠️ Forced purge completed.")
                return False