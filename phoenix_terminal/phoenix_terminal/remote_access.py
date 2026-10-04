"""Private fixed-target SSH adapters; callers never supply connection/options.

Inventory is observational. Railgun is asynchronous, at-most-once on the server,
and may ONLY start an inactive universe. Raw SSH output is never returned.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import base64
import hashlib
import json
import math
import re
import threading
import time

MAX_JOBS = 32
MAX_OUTPUT = 1024 * 1024
_UNIVERSE = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
_STATES = {"queued", "running", "completed", "refused_active", "failed", "outcome_unknown", "cancelled"}


def public_inventory_page(deployment_id, value):
    """Reproject even a buggy adapter; never pass through remote fields."""
    if not isinstance(value, dict) or value.get("deployment_id") != deployment_id:
        raise ValueError("Inventory response scope did not match")
    rows = value.get("universes")
    if not isinstance(rows, list) or len(rows) > 1024:
        raise ValueError("Invalid universe inventory")
    projected, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid universe inventory row")
        name, count, rss, cpu = (row.get(k) for k in ("universe", "agent_count", "rss_bytes", "cpu_percent"))
        if (not isinstance(name, str) or not _UNIVERSE.fullmatch(name) or name in seen
            or row.get("status") != "active" or type(count) is not int or not 0 <= count <= 100000
            or type(rss) is not int or not 0 <= rss <= 2**63 - 1
            or type(cpu) not in (int, float) or not math.isfinite(cpu) or not 0 <= cpu <= 10**7):
            raise ValueError("Invalid universe inventory row")
        seen.add(name)
        projected.append({"universe": name, "status": "active", "agent_count": count,
                          "rss_bytes": rss, "cpu_percent": float(cpu)})
    return {"deployment_id": deployment_id, "universes": projected,
            "live_snapshot": True, "replacement_allowed": False}


def public_launch_status(deployment_id, operation_id, value):
    if (not isinstance(value, dict) or value.get("deployment_id") != deployment_id
        or value.get("operation_id") != operation_id or value.get("state") not in _STATES
        or not isinstance(value.get("remote_request_id"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["remote_request_id"])):
        raise ValueError("Invalid Railgun receipt response")
    code = value.get("exit_code")
    if code is not None and (type(code) is not int or not 0 <= code <= 255):
        raise ValueError("Invalid Railgun exit code")
    return {"deployment_id": deployment_id, "operation_id": operation_id,
            "remote_request_id": value["remote_request_id"], "state": value["state"],
            "exit_code": code, "replacement_allowed": False,
            "live_health_verified": False,
            "operator_reconciliation_required": value["state"] == "outcome_unknown"}


@dataclass(frozen=True)
class FixedTarget:
    deployment_id: str
    universe: str
    destination: str
    revision: str
    profile_json: str = field(repr=False)
    launch_json: str | None = field(default=None, repr=False)
    envelope: bytes | None = field(default=None, repr=False)
    connector: object = field(default=None, repr=False, compare=False)
    command_builder: object = field(default=None, repr=False, compare=False)


def target_from_vault(data, deployment_id, revision, *, launch=False):
    """Called during private decryption, never via a client API; no network."""
    from matrix_gui.modules.railgun.ssh_support import normalize_fingerprint, connect_ssh_profile
    from matrix_gui.modules.railgun.remote_shell import build_remote_matrixd_command, encode_boot_envelope

    deployment = data["deployments"][deployment_id]
    serial = deployment.get("ssh_serial")
    profiles = data.get("registry", {}).get("ssh", {})
    if not isinstance(serial, str) or serial not in profiles or not isinstance(profiles[serial], dict):
        raise ValueError("Saved deployment requires its exact Registry SSH profile")
    source = profiles[serial]
    fields = ("host", "port", "username", "auth_type", "password", "private_key",
              "private_key_passphrase", "trusted_host_fingerprint")
    profile = {key: source[key] for key in fields if key in source}
    host, user = profile.get("host"), profile.get("username")
    port = profile.get("port", 22)
    if (not isinstance(host, str) or not host or len(host) > 253
        or any(c.isspace() or ord(c) < 32 for c in host)
        or not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", user)
        or type(port) is not int or not 1 <= port <= 65535):
        raise ValueError("Saved SSH destination is invalid")
    pin = normalize_fingerprint(profile.get("trusted_host_fingerprint"))
    try:
        digest = base64.b64decode(pin[7:] + "=" * (-len(pin[7:]) % 4), validate=True)
    except ValueError:
        raise ValueError("Saved SSH pin is not a SHA-256 fingerprint") from None
    if len(digest) != 32:
        raise ValueError("Saved SSH pin is not a SHA-256 fingerprint")
    identity = deployment.get("railgun_target_identity")
    if (not isinstance(identity, dict) or str(identity.get("host", "")).lower() != host.lower()
        or type(identity.get("port")) is not int or identity["port"] != port
        or normalize_fingerprint(identity.get("pin")) != pin):
        raise ValueError("Saved deployment SSH binding changed; repair it in Phoenix")
    auth = profile.get("auth_type", "private_key")
    if auth not in {"password", "private_key"}:
        raise ValueError("Terminal SSH requires saved credentials, not an ambient SSH agent")
    credential = profile.get("password" if auth == "password" else "private_key")
    if not isinstance(credential, str) or not credential:
        raise ValueError("Saved SSH authentication is incomplete")
    universe = deployment.get("universe")
    if not isinstance(universe, str) or not _UNIVERSE.fullmatch(universe):
        raise ValueError("Saved universe is invalid")
    options = envelope = None
    if launch:
        saved = deployment.get("railgun_boot_options") or {}
        if not isinstance(saved, dict):
            raise ValueError("Saved Railgun boot options are invalid")
        if saved.get("universe", universe) != universe or saved.get("linux_user", deployment.get("linux_user")) != deployment.get("linux_user"):
            raise ValueError("Saved Railgun options do not match this deployment")
        # A Terminal launch is NOT a GUI reboot/cleanup. Those powers are never
        # inherited even if the original operator deployment used those flags.
        flags = ["--" + name.replace("_", "-") for name in
                 ("verbose", "debug", "rug_pull", "protect_memory")
                 if saved.get(name, deployment.get(name, False)) is True]
        if any(type(saved.get(name, False)) is not bool for name in
               ("verbose", "debug", "rug_pull", "protect_memory")):
            raise ValueError("Saved Railgun flags must be boolean")
        options = {"action": "start", "universe": universe,
                   "linux_user": deployment.get("linux_user"), "boot_flags": flags,
                   "runtime_capabilities": deployment.get("runtime_capabilities"), "require_inactive": True}
        # Fully validate before advertising an adapter, without executing it.
        build_remote_matrixd_command(**options, request_id="0" * 64)
        envelope = encode_boot_envelope(deployment.get("encrypted_bundle"), deployment.get("swarm_key"))
        stored_hash = deployment.get("encrypted_hash")
        if stored_hash is not None:
            actual_hash = hashlib.sha256(json.dumps(deployment["encrypted_bundle"], sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            if stored_hash != actual_hash:
                raise ValueError("Saved sealed directive hash did not match")
    return FixedTarget(deployment_id, universe, f"{user}@{host}:{port} · {universe} · {pin}",
                       revision, json.dumps(profile, sort_keys=True),
                       json.dumps(options, sort_keys=True) if options else None, envelope,
                       connect_ssh_profile, build_remote_matrixd_command)


def _exchange(client, command, check, *, payload=None, on_dispatch=None, timeout=45):
    """Drain bounded output with a wall-clock deadline, checking lease throughout."""
    check()
    channel = client.get_transport().open_session(timeout=10)
    try:
        channel.settimeout(0.5)
        check()
        if on_dispatch:
            on_dispatch()  # Mark uncertain BEFORE exec may reach the server.
        channel.exec_command(command)
        deadline = time.monotonic() + timeout
        def bounded_check():
            check()
            if time.monotonic() >= deadline:
                raise TimeoutError("Fixed SSH operation exceeded its deadline")
        if payload is not None:
            import socket
            offset = 0
            while offset < len(payload):
                bounded_check()
                try:
                    sent = channel.send(payload[offset:offset + 32768])
                except socket.timeout:
                    continue
                if sent <= 0:
                    raise ConnectionError("Boot upload interrupted")
                offset += sent
            channel.shutdown_write()
        output, errors = bytearray(), bytearray()
        while True:
            bounded_check()
            if channel.recv_ready():
                output.extend(channel.recv(32768))
            if channel.recv_stderr_ready():
                errors.extend(channel.recv_stderr(32768))
            if len(output) + len(errors) > MAX_OUTPUT:
                raise ValueError("Fixed SSH output exceeded its limit")
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                code = channel.recv_exit_status()
                if type(code) is not int or not 0 <= code <= 255:
                    raise ConnectionError("SSH exit status missing")
                return code, bytes(output), bytes(errors)
            if channel.closed:
                raise ConnectionError("SSH channel closed without a receipt")
            time.sleep(0.02)
    finally:
        channel.close()


class RemoteOperations:
    def __init__(self, targets):
        self._targets = dict(targets)
        self._jobs = {}
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._connections = threading.BoundedSemaphore(4)

    def _check(self, lease):
        if self._closed.is_set() or not lease():
            raise PermissionError("Connection approval ended")

    def inventory(self, deployment_id, lease):
        target = self._targets[deployment_id]
        self._check(lease)
        if not self._connections.acquire(blocking=False):
            raise RuntimeError("Remote operation concurrency limit reached")
        client = None
        try:
            client, _ = target.connector(json.loads(target.profile_json), timeout=10)
            from matrix_gui.modules.swarms.remote import LIST_COMMAND
            code, output, error = _exchange(client, LIST_COMMAND, lambda: self._check(lease))
            if code != 0 or error.strip():
                raise RuntimeError("Fixed server inventory failed")
            document = json.loads(output)
            if type(document.get("version")) is not int or document["version"] != 1:
                raise ValueError("Unsupported inventory protocol")
            return public_inventory_page(deployment_id, {"deployment_id": deployment_id,
                "universes": document.get("universes")})
        finally:
            if client is not None:
                client.close()
            self._connections.release()

    def launch(self, deployment_id, operation_id, owner, lease):
        self._check(lease)
        target = self._targets[deployment_id]
        if target.launch_json is None:
            raise PermissionError("No Railgun adapter for this deployment")
        key = (owner, deployment_id, operation_id)
        with self._lock:
            if key not in self._jobs:
                if len(self._jobs) >= MAX_JOBS:
                    raise ValueError("Terminal Railgun job table is full; reopen Terminal after reconciling jobs")
                remote_id = hashlib.sha256(json.dumps(["terminal-launch-v1", target.revision,
                    deployment_id, operation_id], separators=(",", ":")).encode()).hexdigest()
                job = {"deployment_id": deployment_id, "operation_id": operation_id,
                       "remote_request_id": remote_id, "state": "queued", "exit_code": None}
                self._jobs[key] = job
                worker = threading.Thread(target=self._launch_worker,
                    args=(target, job, lease), name="TerminalRailgun", daemon=True)
                worker.start()
            return public_launch_status(deployment_id, operation_id, dict(self._jobs[key]))

    def status(self, deployment_id, operation_id, owner, lease):
        self._check(lease)
        with self._lock:
            job = self._jobs.get((owner, deployment_id, operation_id))
            if job is None:
                raise ValueError("No Railgun job exists for this connection; retry launch with the SAME operation ID to consult the durable receipt")
            return public_launch_status(deployment_id, operation_id, dict(job))

    def _launch_worker(self, target, job, lease):
        client = None
        dispatched = False
        acquired = False
        def mark_dispatch():
            nonlocal dispatched
            dispatched = True
        def set_result(state, code=None):
            with self._lock:
                job.update(state=state, exit_code=code)
        try:
            self._check(lease)
            set_result("running")
            acquired = self._connections.acquire(blocking=False)
            if not acquired:
                raise RuntimeError("Remote operation concurrency limit reached")
            client, _ = target.connector(json.loads(target.profile_json), timeout=10)
            self._check(lease)
            command = target.command_builder(**json.loads(target.launch_json), request_id=job["remote_request_id"])
            code, output, _ = _exchange(client, command, lambda: self._check(lease),
                payload=target.envelope, on_dispatch=mark_dispatch, timeout=180)
            # Exit alone isn't proof of a receipt (preflight might have failed).
            completion = f"[RAILGUN][COMPLETED] request={job['remote_request_id']} exit={code}".encode()
            replay = (f"[RAILGUN][REPLAY] Request already completed (exit={code}); no boot repeated. "
                      "This is not a live health check.").encode()
            trailer = output.rstrip().splitlines()[-1] if output.strip() else b""
            if trailer not in (completion, replay):
                set_result("outcome_unknown", code)
            else:
                set_result("refused_active" if code == 73 else "completed" if code == 0 else "failed", code)
        except PermissionError:
            set_result("outcome_unknown" if dispatched else "cancelled")
        except Exception:
            set_result("outcome_unknown" if dispatched else "failed")
        finally:
            if client is not None:
                client.close()
            if acquired:
                self._connections.release()

    def close(self):
        self._closed.set()
        self._targets.clear()

    def operator_statuses(self):
        """Private presenter view, including uncertain jobs after grant expiry."""
        with self._lock:
            return tuple(public_launch_status(job["deployment_id"], job["operation_id"], dict(job))
                         for job in self._jobs.values())
