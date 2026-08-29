"""Harmless MCP stdio server used by the isolated bridge compatibility test."""

from mcp.server import MCPServer


server = MCPServer("matrixswarm-mcp-reflex-test")


@server.tool()
def echo(message: str) -> dict[str, str]:
    """Return the supplied message."""
    return {"message": message}


@server.tool()
def hidden() -> dict[str, bool]:
    """Exist so the bridge can prove that discovery filtering works."""
    return {"visible": False}


if __name__ == "__main__":
    server.run(transport="stdio")
