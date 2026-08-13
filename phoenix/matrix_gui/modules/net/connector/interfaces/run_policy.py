from dataclasses import dataclass

@dataclass
class RunPolicy:
    # What the connector *is* (looping vs one-shot)
    connector_persistent: bool
    # Should it auto-start at session boot?
    auto_start: bool
    # Should the watchdog monitor/restart it?
    monitor: bool
    # If True, it should only run when a packet is provided
    requires_packet: bool = False
    # If false, launcher should not start it (missing config, not selected, etc.)
    ready: bool = True
    # Reason for logging / UI
    reason: str = ""