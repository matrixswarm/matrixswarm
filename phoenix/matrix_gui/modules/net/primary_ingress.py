"""Select the same initial receive route for startup and the session UI."""


def select_primary_ingress(deployment):
    """Return the primary payload.reception agent, or None.

    The last explicitly marked primary wins in deployment order, matching the
    Routes UI. Without an explicit primary, prefer WebSocket, then the first
    receive route. Ignore records without a UID because they cannot be launched.
    """
    incoming = [
        agent for agent in deployment.get("agents", [])
        if agent.get("universal_id")
        and ((agent.get("connection") or {}).get("channel") or "").strip().lower()
        == "payload.reception"
    ]
    for agent in reversed(incoming):
        if (agent.get("connection") or {}).get("default_payload_reception"):
            return agent

    for agent in incoming:
        proto = ((agent.get("connection") or {}).get("proto") or "").strip().lower()
        name = (agent.get("name") or "").strip().lower()
        if proto == "wss" or "websocket" in name:
            return agent

    return incoming[0] if incoming else None
