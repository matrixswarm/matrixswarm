"""Serialize Matrix transaction changes and publish signed authorization state.

Reaper reads this state only while holding the same universe lifecycle fence.
The pending marker makes interrupted/ambiguous tree writes fail closed.
"""
import copy
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import os
import secrets
import stat
import threading
from Crypto.PublicKey import RSA

from core.python_core.lifecycle_fence import LifecycleFence, GENERATION_ENV
from core.python_core.safe_paths import child_directory, open_beneath, write_file_at
from core.python_core.utils.crypto_utils import sign_data, verify_signed_payload

_init_lock = threading.Lock()
_AUTH_FILE = "reaper_authorization.json"
_PENDING_FILE = "reaper_authorization.pending"


class ReapTransactionError(RuntimeError):
    pass


def _state(self):
    with _init_lock:
        if not hasattr(self, "_reap_transaction_mutex"):
            self._reap_transaction_mutex = threading.RLock()
            self._reap_transaction_local = threading.local()
    return self._reap_transaction_mutex, self._reap_transaction_local


def _snapshot(self):
    tree = getattr(self, "_agent_tree_master", None)
    return copy.deepcopy(tree.root) if tree is not None else None, copy.deepcopy(getattr(self, "meta", {}))


def _fingerprint(snapshot):
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _restore(self, snapshot):
    root, meta = copy.deepcopy(snapshot)
    if root is not None and getattr(self, "_agent_tree_master", None) is not None:
        self._agent_tree_master.root = root
        self._agent_tree_master.reparse()
    self.meta = meta


def _projection(self):
    tree = getattr(self, "_agent_tree_master", None)
    result = {}
    if tree is None:
        return result
    for uid, node in tree.nodes.items():
        if not isinstance(node, dict):
            raise ReapTransactionError("Malformed agent tree")
        life = node.get("lifecycle_status", {})
        if not isinstance(life, dict):
            raise ReapTransactionError("Malformed lifecycle state")
        if life.get("transaction_id"):
            result[uid] = {"transaction_id": life.get("transaction_id"), "stage": life.get("op_stage"),
                           "op": life.get("op"), "locked": bool(life.get("locked")),
                           "target_snapshot": copy.deepcopy(life.get("reap_target"))}
    return result


def _signed_map(self, fence_state, status):
    private = getattr(self, "matrix_priv_obj", None)
    if private is None:
        raise ReapTransactionError("Matrix signing capability is required for lifecycle authorization")
    payload = {"version": 1, "universe": self.command_line_args["universe"],
               "boot_id": fence_state["boot_id"], "generation": fence_state["generation"],
               "revision": secrets.token_hex(32), "status": status,
               "targets": _projection(self) if status == "committed" else {}}
    payload["sig"] = sign_data(payload, private)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 1024 * 1024:
        raise ReapTransactionError("Lifecycle authorization state is too large")
    return payload, encoded


def _write_map(self, encoded):
    with child_directory(self._runtime_comm_fd, "directive", create=True) as directive_fd:
        write_file_at(directive_fd, _AUTH_FILE, encoded, mode=0o600, durable=True)


def _mark_pending(self):
    with child_directory(self._runtime_comm_fd, "directive", create=True) as directory_fd:
        write_file_at(directory_fd, _PENDING_FILE, b"pending\n", mode=0o600, durable=True)


def _finish_pending(self):
    # Once unlink succeeds the saved tree and its signed map are already
    # durable. A subsequent directory-fsync failure cannot undo that commit.
    with child_directory(self._runtime_comm_fd, "directive") as directory_fd:
        os.unlink(_PENDING_FILE, dir_fd=directory_fd)
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            try:
                self.log("[REAPER-TXN] State committed; pending-marker directory sync failed.", error=exc, level="ERROR")
            except Exception:
                pass


def read_reap_authorization(matrix_comm_fd, *, public_key, universe, boot_id, generation, allow_prior_generation=False):
    """Read and verify a committed signed projection from Matrix's comm FD."""
    with child_directory(matrix_comm_fd, "directive") as directory_fd:
        try:
            os.stat(_PENDING_FILE, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ReapTransactionError("Lifecycle authorization is pending; operator recovery is required")
        fd = open_beneath(directory_fd, _AUTH_FILE, os.O_RDONLY | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ReapTransactionError("Unsafe lifecycle authorization file")
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                encoded = stream.read(1024 * 1024 + 1)
            if len(encoded) > 1024 * 1024:
                raise ReapTransactionError("Lifecycle authorization file is too large")
            payload = json.loads(encoded)
        finally:
            if fd >= 0:
                os.close(fd)
    if (not isinstance(payload, dict) or set(payload) != {"version", "universe", "boot_id", "generation", "revision", "status", "targets", "sig"}
            or payload["version"] != 1 or payload["universe"] != universe or payload["boot_id"] != boot_id
            or (payload["generation"] != generation and not allow_prior_generation) or payload["status"] != "committed"
            or not isinstance(payload["revision"], str) or len(payload["revision"]) != 64
            or any(c not in "0123456789abcdef" for c in payload["revision"])
            or not isinstance(payload["targets"], dict) or not isinstance(payload["sig"], str)):
        raise ReapTransactionError("Lifecycle authorization is pending, invalid, or belongs to another boot")
    key = RSA.import_key(public_key) if isinstance(public_key, (str, bytes)) else public_key
    try:
        verify_signed_payload(payload, payload["sig"], key)
    except Exception as exc:
        raise ReapTransactionError("Lifecycle authorization signature is invalid") from exc
    return payload, encoded


def note_reap_save_attempt(self):
    local = getattr(self, "_reap_transaction_local", None)
    context = getattr(local, "context", None)
    if context is not None:
        context["save_attempted"] = True
        context["saved_fingerprint"] = None


def note_reap_save_success(self):
    local = getattr(self, "_reap_transaction_local", None)
    context = getattr(local, "context", None)
    if context is not None:
        context["saved_fingerprint"] = _fingerprint(_snapshot(self))


def commit_reap_mutation(self):
    _, local = _state(self)
    context = getattr(local, "context", None)
    if context is None:
        raise ReapTransactionError("No guarded lifecycle transaction is active")
    if context["saved_fingerprint"] != _fingerprint(_snapshot(self)):
        raise ReapTransactionError("Lifecycle tree has not been durably saved")
    if context["depth"] == 1:
        context["committed"] = True


def defer_reap_side_effect(self, callback):
    _, local = _state(self)
    context = getattr(local, "context", None)
    if context is None or not callable(callback):
        raise ReapTransactionError("Side effect requires a guarded lifecycle transaction")
    context["deferred"].append(callback)


def defer_reap_abort(self, callback):
    _, local = _state(self)
    context = getattr(local, "context", None)
    if context is None or not callable(callback):
        raise ReapTransactionError("Abort callback requires a guarded lifecycle transaction")
    context["abort"].append(callback)


@contextmanager
def _guard(self):
    mutex, local = _state(self)
    deferred = []
    context = None
    try:
        with mutex:
            current = getattr(local, "context", None)
            if current is not None:
                current["depth"] += 1
                try:
                    yield current
                finally:
                    current["depth"] -= 1
                return
            generation = os.environ.get(GENERATION_ENV)
            if not generation:
                raise ReapTransactionError("Lifecycle generation is unavailable; restart the universe safely")
            fence = LifecycleFence(self.path_resolution["install_path"], self.command_line_args["universe"])
            with fence.exclusive(expected_generation=generation):
                fence_state = fence.read_state()
                if getattr(self, "_agent_tree_master", None) is None:
                    if not self.get_agent_tree_master():
                        raise ReapTransactionError("Cannot load the authenticated Matrix tree")
                before = _snapshot(self)
                try:
                    old = read_reap_authorization(self._runtime_comm_fd, public_key=self.matrix_pub,
                                                  universe=self.command_line_args["universe"],
                                                  boot_id=fence_state["boot_id"], generation=generation,
                                                  allow_prior_generation=True)
                except FileNotFoundError:
                    old = None
                if old is not None and old[0]["generation"] != generation:
                    # A safely restarted universe may reuse this boot's comm
                    # directory. Authenticate the old record, then establish
                    # a fresh baseline under the new lifecycle generation.
                    old = None
                if old is not None and old[0]["targets"] != _projection(self):
                    raise ReapTransactionError("Committed lifecycle authorization disagrees with the Matrix tree")
                _mark_pending(self)
                _, pending = _signed_map(self, fence_state, "pending")
                _write_map(self, pending)
                self._reap_committed_authorization = None
                context = {"depth": 1, "committed": False, "save_attempted": False,
                           "saved_fingerprint": None, "deferred": [], "abort": []}
                local.context = context
                try:
                    yield context
                    if context["committed"]:
                        if context["saved_fingerprint"] != _fingerprint(_snapshot(self)):
                            raise ReapTransactionError("Lifecycle tree changed after its confirmed save")
                        if old is not None and old[0]["targets"] == _projection(self):
                            # Unrelated metadata (for example heartbeat scans)
                            # must not invalidate an in-flight stage proof.
                            payload, encoded = old
                        else:
                            payload, encoded = _signed_map(self, fence_state, "committed")
                        _write_map(self, encoded)
                        _finish_pending(self)
                        self._reap_committed_authorization = (payload, encoded)
                        deferred = context["deferred"]
                    elif not context["save_attempted"] and _fingerprint(_snapshot(self)) == _fingerprint(before):
                        if old is not None:
                            _write_map(self, old[1])
                            _finish_pending(self)
                            self._reap_committed_authorization = old
                        else:
                            # Upgrade/bootstrap from the authenticated tree:
                            # establish a fresh durable baseline before the
                            # first challenge is allowed to succeed.
                            if not self.save_agent_tree_master():
                                raise ReapTransactionError("Could not establish lifecycle authorization baseline")
                            if context["saved_fingerprint"] != _fingerprint(_snapshot(self)):
                                raise ReapTransactionError("Lifecycle baseline was not durably confirmed")
                            payload, encoded = _signed_map(self, fence_state, "committed")
                            _write_map(self, encoded)
                            _finish_pending(self)
                            self._reap_committed_authorization = (payload, encoded)
                        deferred = context["deferred"]
                    else:
                        _restore(self, before)
                        raise ReapTransactionError("Lifecycle change was not durably committed; authorization is paused")
                except BaseException:
                    _restore(self, before)
                    raise
                finally:
                    del local.context
    except BaseException:
        if context is not None:
            for callback in context["abort"]:
                try:
                    callback()
                except Exception:
                    pass
        raise
    for callback in deferred:
        try:
            callback()
        except Exception as exc:
            try:
                self.log("[REAPER-TXN] State committed, but a follow-up notification failed.", error=exc, level="ERROR")
            except Exception:
                pass


def reap_mutation(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with _guard(self):
            return method(self, *args, **kwargs)
    return guarded
