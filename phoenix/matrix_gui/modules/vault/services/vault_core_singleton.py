# Commander Edition – Unified, Protected, Single-Authority Vault System
import json
import threading
import logging
import traceback
from collections import deque
from pathlib import Path
from copy import deepcopy
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.vault_stores.phoenix_vault_core import PhoenixVaultCore as StoreCore


class VaultSavedReopenRequired(RuntimeError):
    """Disk commit succeeded but the live authority could not publish it."""


class _TransformReservation:
    """Distinguish a single detached transform from a queued workspace write."""
    def __init__(self, section, callback):
        self.section = section
        self.callback = callback

class VaultCoreSingleton:
    _instance = None
    _lock = threading.RLock()

    @classmethod
    def initialize(cls, vault_data, password, vault_path, *, ai_mode=False):
        if type(ai_mode) is not bool:
            raise ValueError("ai_mode must be a boolean")
        with cls._lock:
            if cls._instance is not None:
                if cls._instance._workspace_active is not None or cls._instance._workspace_queue:
                    raise RuntimeError("Wait for pending workspace writes before opening another vault")
                cls._instance.close()
                EventBus.off("vault.closed", cls._instance._on_closed)
            cls._instance = cls(vault_data, password, vault_path, ai_mode=ai_mode)
            EventBus.on("vault.closed", cls._instance._on_closed)
        print("[VAULT-CORE] Initialized central vault authority.")
        EventBus.emit("vault.core.ready")
        return cls._instance

    @classmethod
    def get(cls):
        if not cls._instance:
            raise RuntimeError("Vault not initialized.")
        return cls._instance

    # -----------------------------
    def __init__(self, vault_data, password, vault_path, *, ai_mode=False):

        if not isinstance(vault_data, dict):
            raise ValueError("Vault runtime requires a dictionary")
        self.password = password
        self.vault_path = Path(vault_path)
        self.data = deepcopy(vault_data)
        self.last_good = deepcopy(self.data)
        self._closed = False
        self._listeners = set()
        self._workspace_queue = deque()
        self._workspace_active = None
        self._workspace_writer = None
        self._transform_writer = None

        # Construction errors must propagate; never publish half an authority.
        self.store_core = StoreCore(self)

        # Compose one authority in this vault. The singleton facade resolves
        # this object; it never owns a second credential store or runtime.
        from matrix_gui.modules.access_control.access_control_singleton import AccessControlSingleton
        self._access_control = AccessControlSingleton(self, ai_mode=ai_mode)

    @property
    def access_control(self):
        return self._access_control

    def close(self):
        """Revoke this vault's authority before any session teardown."""
        with self._lock:
            self._closed = True
            self._access_control.close()

    # -----------------------------
    def _on_closed(self, **kwargs):
        self.close()

    def get_store(self, name):
        return self.store_core.get_store(name)

    def read(self, safe=True):
        return deepcopy(self.data) if safe else self.data

    def session_snapshot(self):
        """Legacy session projection; parent-owned authorization never crosses IPC."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Vault is closed")
            if self.access_control.ai_mode:
                raise PermissionError("Legacy session snapshots are blocked in AI Mode")
            return deepcopy({
                key: value for key, value in self.data.items() if key != "access_control"
            })

    def get_section(self, key):
        """
        Return the live vault section when idle, or a detached snapshot while
        an asynchronous write is active or queued.
        """
        with self._lock:
            # During a detached write, callers may inspect a snapshot but
            # cannot mutate the live section through a newly acquired handle.
            if self._workspace_active is not None or self._workspace_queue:
                return deepcopy(self.data.get(key, {}))
            return self.data.setdefault(key, {})

    def snapshot(self, key):
        """Return a deep copy of the vault section for read-only use."""
        from copy import deepcopy
        return deepcopy(self.data.get(key, {}))

    def listen(self, event_name: str):
        """Register a vault event to emit when data changes."""
        self._listeners.add(event_name)
        print(f"[VAULT-CORE] Event listener registered: {event_name}")

    def _emit_to_listeners(self):
        for evt in self._listeners:
            EventBus.emit(evt, vcs=self)

    # -----------------------------
    def transform_section(self, key, transform):
        """Recheck and replace one section under the same lock as persistence.

        The callback receives a detached snapshot; it must not perform I/O.
        Closed/busy vaults reject before the callback, just like patch().
        """
        with self._lock:
            if self._closed or self._workspace_active is not None or self._workspace_queue:
                return False
            candidate = transform(deepcopy(self.data.get(key, {})))
            if candidate == self.data.get(key, {}):
                return True
            return self.patch(key, candidate)

    def transform_section_async(self, key, transform, callback):
        """Persist a detached section transform without blocking the Qt thread.

        ``transform(detached_section)`` returns ``(replacement, result)`` on
        the writer thread. ``callback(result, error)`` runs on the Qt thread.
        A submitted write is never cancelled or considered timed out.
        """
        from PyQt6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("Vault transforms must be requested on the GUI thread")
        if not isinstance(key, str) or not key or not callable(transform) or not callable(callback):
            raise ValueError("Invalid vault transform request")
        with self._lock:
            if self._closed:
                raise RuntimeError("The vault is closed")
            if self.access_control.ai_mode and key != "access_control":
                raise PermissionError("Vault mutation is blocked in AI Mode")
            if self._workspace_active is not None or self._workspace_queue:
                raise RuntimeError("The vault is busy saving another change")
            snapshot = deepcopy(self.data)
            if self._transform_writer is None:
                from .vault_transform_writer import VaultTransformWriter
                self._transform_writer = VaultTransformWriter(self._transform_written)
            self._workspace_active = _TransformReservation(key, callback)
            try:
                self._transform_writer.submit(snapshot, self.password, str(self.vault_path), key, transform)
            except Exception:
                self._workspace_active = None
                raise

    def _transform_written(self, result, candidate, error):
        with self._lock:
            reservation = self._workspace_active
            if not isinstance(reservation, _TransformReservation):
                raise RuntimeError("Unexpected vault transform completion")
            self._workspace_active = None
            if error is None:
                candidate, last_good = candidate
                self.last_good = last_good
                try:
                    live = self.data.get(reservation.section)
                    if isinstance(live, dict) and isinstance(candidate, dict):
                        live.clear()
                        live.update(candidate)
                    else:
                        self.data[reservation.section] = candidate
                    if not self._closed:
                        EventBus.emit("vault.core.update")
                except Exception:
                    # Disk was already replaced. Never report a failed save or
                    # allow another write from potentially inconsistent RAM.
                    self._closed = True
                    try:
                        self._access_control.close()
                    except Exception:
                        pass
                    error = VaultSavedReopenRequired("The vault was saved, but its in-memory state could not be updated. Reopen the vault before saving again.")
        try:
            reservation.callback(result if error is None else None, error)
        except Exception as exc:
            logging.getLogger(__name__).error("Vault transform completion callback failed (%s)", type(exc).__name__)
        finally:
            self._start_workspace_write()

    def patch(self, key, value):
        """Single choke point — all mutations flow through here."""
        with self._lock:
            if self._closed:
                return False
            if self.access_control.ai_mode and key != "access_control":
                # The AI pilot has no typed registry/deployment/workspace
                # mutation adapter. Reject at persistence, not just the button.
                return False

            # Legacy synchronous callers must not overwrite a snapshot which
            # is still being saved. They retain their existing rejection path.
            if self._workspace_active is not None or self._workspace_queue:
                return False

            if value is None:
                print(f"[VAULT][PROTECT] Refusing to remove section {key}.")
                return False

            candidate = deepcopy(self.data)
            candidate[key] = deepcopy(value)
            raw = json.dumps(candidate)
            if len(raw) < 200:
                print("[VAULT][PROTECT] Refusing to shrink vault unnaturally.")
                self.data = deepcopy(self.last_good)
                return False

            # EventBus swallows listener exceptions, so require an explicit
            # acknowledgement from the synchronous writer before publishing.
            receipt = {"saved": False}
            EventBus.emit("vault.update",
                          data=candidate,
                          password=self.password,
                          vault_path=str(self.vault_path),
                          receipt=receipt)
            if not receipt["saved"]:
                return False
            self.data[key] = deepcopy(candidate[key])
            self.last_good = deepcopy(self.data)

            EventBus.emit("vault.core.update")

            return True

    def save_workspace_async(self, entry, callback):
        """Queue one detached workspace edit; callback runs on the Qt thread."""
        from PyQt6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("Workspace saves must be requested on the GUI thread")
        if self._closed:
            raise RuntimeError("The workspace vault is closed")
        if self.access_control.ai_mode:
            raise PermissionError("Workspace edits are blocked in AI Mode")
        if not isinstance(entry, dict) or not isinstance(entry.get("uuid"), str) or not entry["uuid"].strip():
            raise ValueError("Workspace save requires a nonempty string identity")
        if not callable(callback):
            raise TypeError("Workspace save requires a completion callback")
        if not isinstance(self.data.get("workspaces", {}), dict):
            raise ValueError("Vault workspaces section is malformed; save refused")
        from .workspace_writer import WorkspaceWriter
        if self._workspace_writer is None:
            self._workspace_writer = WorkspaceWriter(self._workspace_written)
        self._workspace_queue.append((deepcopy(entry), callback))
        self._start_workspace_write()

    def _start_workspace_write(self):
        if self._closed:
            while self._workspace_queue:
                _, callback = self._workspace_queue.popleft()
                try:
                    callback(False)
                except Exception as exc:
                    logging.getLogger(__name__).error("Closed vault workspace callback failed (%s)", type(exc).__name__)
            return
        if self._workspace_active is not None or not self._workspace_queue:
            return
        entry, callback = self._workspace_queue.popleft()
        snapshot = deepcopy(self.data)
        snapshot.setdefault("workspaces", {})[entry["uuid"]] = entry
        self._workspace_active = (entry, callback)
        try:
            self._workspace_writer.submit(snapshot, self.password, str(self.vault_path))
        except Exception as exc:
            self._workspace_written(exc)

    def _workspace_written(self, error):
        entry, callback = self._workspace_active
        self._workspace_active = None
        if error is None:
            self.data.setdefault("workspaces", {})[entry["uuid"]] = deepcopy(entry)
            self.last_good = deepcopy(self.data)
            if not self._closed:
                EventBus.emit("vault.core.update")
        try:
            callback(error is None)
        except Exception as exc:
            # The write result remains authoritative even if its UI consumer fails.
            frames = traceback.extract_tb(exc.__traceback__)
            locations = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in frames)
            logging.getLogger(__name__).error(
                "Workspace completion callback failed (%s); disk write success=%s\n%s",
                type(exc).__name__, error is None, locations)
        finally:
            self._start_workspace_write()

    def batch(self, *stores):
        """
        Execute multiple store commits atomically.
        If ANY fail validation, NO changes are persisted.
        """
        snapshots = {s.section_key: s.get_data() for s in stores}

        # Validate everything first
        for store in stores:
            if not store.validate_store():
                return False
            if not store.cross_validate():
                return False

        # Commit sequentially
        for store in stores:
            if not store.commit():
                # rollback
                for key, data in snapshots.items():
                    self.patch(key, data)
                return False

        return True
