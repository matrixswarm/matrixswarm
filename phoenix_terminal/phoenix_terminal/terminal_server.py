"""Independent loopback endpoint for Terminal connection requests."""

from pathlib import Path

from .bridge.server import BridgeServer


class TerminalRequestServer(BridgeServer):
    """Use a separate descriptor so the legacy inventory endpoint cannot mix in."""

    @property
    def connection_path(self) -> Path:
        return self._data_dir / "terminal-access.json"
