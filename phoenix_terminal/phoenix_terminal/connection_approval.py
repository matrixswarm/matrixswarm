"""Pure connection-approval contracts for the independent Terminal runtime."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
import threading


MIN_LIFETIME_SECONDS = 60
MAX_LIFETIME_SECONDS = 3600
MAX_PENDING_REQUESTS = 8
CURRENT_OPERATIONS = frozenset({"alerts.read", "swarms.list", "railgun.launch", "agents.list", "logs.read", "sessions.list", "sessions.open"})
_REVISION = re.compile(r"^[0-9a-f]{64}$")


def _plain(value: object, field: str, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    if len(value) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field} contains unsafe display text")
    return value


@dataclass(frozen=True)
class ApprovalResource:
    deployment_id: str
    label: str
    operations: tuple[str, ...] = ()
    fixed_destination: str = ""

    def __post_init__(self):
        _plain(self.deployment_id, "deployment_id", 256)
        _plain(self.label, "resource label", 256)
        if self.fixed_destination:
            _plain(self.fixed_destination, "fixed destination", 512)
        if not isinstance(self.operations, tuple):
            raise ValueError("Resource operations must be a tuple")
        if len(self.operations) != len(set(self.operations)):
            raise ValueError("Resource operations contain duplicates")
        unknown = set(self.operations).difference(CURRENT_OPERATIONS)
        if unknown:
            raise ValueError(
                f"Unsupported resource operation(s): {', '.join(sorted(unknown))}"
            )


@dataclass(frozen=True)
class ConnectionApprovalRequest:
    request_id: str
    client_label: str
    vault_label: str
    vault_revision: str
    resources: tuple[ApprovalResource, ...]
    operations: tuple[str, ...]
    lifetime_seconds: int

    def __post_init__(self):
        _plain(self.request_id, "request_id", 128)
        _plain(self.client_label, "client label")
        _plain(self.vault_label, "vault label")
        if not isinstance(self.vault_revision, str) or not _REVISION.fullmatch(
            self.vault_revision
        ):
            raise ValueError("vault_revision must be a SHA-256 hex digest")
        if not isinstance(self.resources, tuple) or not self.resources:
            raise ValueError("Approval must describe at least one prepared deployment")
        ids = [resource.deployment_id for resource in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("Approval resources contain duplicate deployment IDs")
        if not isinstance(self.operations, tuple):
            raise ValueError("Approval operations must be a tuple")
        if len(self.operations) != len(set(self.operations)):
            raise ValueError("Approval operations contain duplicates")
        unknown = set(self.operations).difference(CURRENT_OPERATIONS)
        if unknown:
            raise ValueError(f"Unsupported approval operation(s): {', '.join(sorted(unknown))}")
        resource_operations = {
            operation
            for resource in self.resources
            for operation in resource.operations
        }
        if resource_operations != set(self.operations):
            raise ValueError("Approval operations do not match the resource scopes")
        if type(self.lifetime_seconds) is not int or not (
            MIN_LIFETIME_SECONDS
            <= self.lifetime_seconds
            <= MAX_LIFETIME_SECONDS
        ):
            raise ValueError("Approval lifetime must be an integer from 60 to 3600 seconds")


@dataclass(frozen=True)
class ApprovalDecision:
    request_id: str
    allowed: bool
    reason: str


class PendingApprovalQueue:
    """Bounded, deduplicated queue owned only by the Terminal process."""

    def __init__(self, maximum: int = MAX_PENDING_REQUESTS):
        if type(maximum) is not int or maximum < 1 or maximum > MAX_PENDING_REQUESTS:
            raise ValueError(f"maximum must be from 1 to {MAX_PENDING_REQUESTS}")
        self._maximum = maximum
        self._pending: OrderedDict[str, ConnectionApprovalRequest] = OrderedDict()
        self._lock = threading.RLock()

    def enqueue(self, request: ConnectionApprovalRequest) -> bool:
        if not isinstance(request, ConnectionApprovalRequest):
            raise TypeError("request must be a ConnectionApprovalRequest")
        with self._lock:
            existing = self._pending.get(request.request_id)
            if existing is not None:
                if existing != request:
                    raise PermissionError("Request ID was reused with different approval data")
                return False
            if len(self._pending) >= self._maximum:
                raise RuntimeError("Terminal approval queue is full")
            self._pending[request.request_id] = request
            return True

    def next(self) -> ConnectionApprovalRequest | None:
        with self._lock:
            return next(iter(self._pending.values()), None)

    def resolve(self, request_id: str, allowed: bool, reason: str) -> ApprovalDecision:
        if type(allowed) is not bool:
            raise TypeError("allowed must be true or false")
        _plain(reason, "decision reason", 80)
        with self._lock:
            if request_id not in self._pending:
                raise PermissionError("Approval request is no longer pending")
            self._pending.pop(request_id)
        return ApprovalDecision(request_id=request_id, allowed=allowed, reason=reason)

    def revoke_all(self, reason: str = "terminal locked") -> tuple[ApprovalDecision, ...]:
        _plain(reason, "decision reason", 80)
        with self._lock:
            request_ids = tuple(self._pending)
            self._pending.clear()
        return tuple(
            ApprovalDecision(request_id=item, allowed=False, reason=reason)
            for item in request_ids
        )

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)
