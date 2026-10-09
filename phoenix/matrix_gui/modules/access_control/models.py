"""Small immutable values shared by the authority and encrypted vault store."""

from dataclasses import dataclass, field, fields
import re


MAX_PERMISSIONS = 128
MAX_CREDENTIALS = 128
ACTION_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,5}\Z")
TARGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class AccessDenied(PermissionError):
    """No current authorization for this exact operation."""


class AccessControlError(RuntimeError):
    """Invalid configuration or unavailable parent authority."""


class VaultWriteError(AccessControlError):
    """The vault did not acknowledge a durable write."""


def check_action(action):
    if not isinstance(action, str) or len(action) > 96 or not ACTION_NAME.fullmatch(action):
        raise ValueError("Use an exact dotted action name, such as agents.logs.read")


@dataclass(frozen=True)
class Target:
    """Exact identifiers; an omitted identifier never means a wildcard."""

    deployment_id: str | None = None
    session_id: str | None = None
    runtime_id: str | None = None
    agent_id: str | None = None
    panel_id: str | None = None

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if value is not None and (
                not isinstance(value, str) or not TARGET_ID.fullmatch(value)
            ):
                raise ValueError(f"Invalid {item.name}")

    def to_record(self):
        return {
            item.name: getattr(self, item.name)
            for item in fields(self) if getattr(self, item.name) is not None
        }

    @classmethod
    def from_record(cls, record):
        if not isinstance(record, dict) or set(record) - set(TARGET_FIELDS):
            raise ValueError("Invalid authorization target")
        if any(value is None for value in record.values()):
            raise ValueError("Omit unset target identifiers")
        return cls(**record)


TARGET_FIELDS = tuple(item.name for item in fields(Target))


@dataclass(frozen=True)
class Permission:
    action: str
    target: Target = field(default_factory=Target)

    def __post_init__(self):
        check_action(self.action)
        if not isinstance(self.target, Target):
            raise ValueError("A permission requires a Target")

    def to_record(self):
        return {"action": self.action, "target": self.target.to_record()}

    @classmethod
    def from_record(cls, record):
        if not isinstance(record, dict) or set(record) != {"action", "target"}:
            raise ValueError("Invalid permission record")
        return cls(record["action"], Target.from_record(record["target"]))


def permissions_tuple(values):
    if not isinstance(values, (tuple, list)) or len(values) > MAX_PERMISSIONS:
        raise ValueError(f"Use at most {MAX_PERMISSIONS} exact permissions")
    if any(not isinstance(value, Permission) for value in values):
        raise ValueError("Expected Permission values")
    if len(set(values)) != len(values):
        raise ValueError("Duplicate permissions are not allowed")
    return tuple(values)


@dataclass(frozen=True)
class Credential:
    """Returned once on creation; never print, log, or persist the secret elsewhere."""

    credential_id: str
    label: str
    secret: str = field(repr=False)


@dataclass(frozen=True)
class Grant:
    connection_id: str
    expires_at: str
    token: str = field(repr=False)
