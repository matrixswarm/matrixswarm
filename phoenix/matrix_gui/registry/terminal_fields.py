"""Window-scoped Terminal Mode fields, never an access-control switch.

Terminal-specific record metadata is authored here for future terminal adapters.
Neither this mode nor saved metadata enables an operation or an endpoint.
Only editors opened from Terminal Mode show these fields. Legacy vault UI
preferences are ignored.
"""
from copy import deepcopy
import base64
import binascii
import ipaddress


def fields_visible(core=None, *, terminal_mode=False):
    if terminal_mode is not True:
        return False
    if core is None:
        from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
        try:
            core = VaultCoreSingleton.get()
        except RuntimeError:
            return False
    if getattr(core, "_closed", False):
        return False
    return True


def ssh_target(record):
    """Public server identity for editor matching, without resolving DNS or I/O."""
    host = record.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("Target server requires a host.")
    host = host.strip()
    if any(character.isspace() or ord(character) < 32 for character in host):
        raise ValueError("Target server host must not contain whitespace or controls.")
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        host = host.rstrip(".").lower()
    if not host:
        raise ValueError("Target server requires a host.")
    port = record.get("port", 22)
    if isinstance(port, bool) or not isinstance(port, (int, str)):
        raise ValueError("Target server port must be an integer.")
    try:
        port = int(port)
    except ValueError:
        raise ValueError("Target server port must be an integer.") from None
    if not 1 <= port <= 65535:
        raise ValueError("Target server port is out of range.")
    pin = record.get("trusted_host_fingerprint")
    if not isinstance(pin, str) or not pin.strip().startswith("SHA256:"):
        raise ValueError("A pinned SHA256 host fingerprint is required.")
    encoded = pin.strip()[7:].rstrip("=")
    try:
        digest = base64.b64decode(encoded + "=", validate=True)
        if len(digest) != 32 or base64.b64encode(digest).decode().rstrip("=") != encoded:
            raise ValueError
    except (ValueError, binascii.Error):
        raise ValueError("Target server requires a canonical SHA256 host fingerprint.") from None
    return {"host": host, "port": port, "trusted_host_fingerprint": "SHA256:" + encoded}


def merge_record_metadata(original, edited):
    """Preserve unrelated record metadata while accepting editor-owned changes."""
    metadata = deepcopy(original.get("meta", {}))
    incoming = edited.get("meta", {})
    if not isinstance(metadata, dict) or not isinstance(incoming, dict):
        raise ValueError("Registry metadata must be an object.")
    metadata.update(deepcopy(incoming))
    edited["meta"] = metadata
    return edited
