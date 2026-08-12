from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class ConnectorPolicy:
    # Policy knobs (what Phoenix wants)
    auto_start: bool = False
    monitor: bool = False

    # Behavior expectations
    requires_packet: bool = False
    connector_persistent: bool = False  # informational: what the connector is

    # Readiness gate (no thrash)
    ready: bool = True
    reason: str = ""

@dataclass
class ConnectorSpec:
    uid: str
    class_path: str
    context: Dict[str, Any] = field(default_factory=dict)
    policy: ConnectorPolicy = field(default_factory=ConnectorPolicy)

    # Runtime bookkeeping (owned by launcher)
    thread_id: Optional[str] = None
    last_error: Optional[str] = None