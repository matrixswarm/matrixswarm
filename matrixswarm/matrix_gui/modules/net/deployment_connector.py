import threading, uuid, logging
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from .connector.https.https import HTTPSConnector
from .connector.wss.wss import WSSConnector
from .entity.adapter.agent_connection_wrapper import AgentConnectionWrapper
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.dispatcher.session_bus import SessionBus

from matrix_gui.core.connector_bus import ConnectorBus

# later: from discord_connector import connect_discord, etc.

log = logging.getLogger("deployment_connector")

SUPPORTED_PROTOS = {"https", "wss"}

# Map proto → connector function
CONNECTOR_MAP = {
    "https": HTTPSConnector(),
    "wss": WSSConnector(),
    # future: "discord": connect_discord,
    # future: "telegram": connect_telegram,
    # future: "slack": connect_slack,
    # future: "sms": connect_sms,
}

def start_session(deployment, dep_id=None):
    return _connect_single(deployment, dep_id)

def on_connect(dep_id=None, vault_data=None, **kwargs):
    """
    Handles deployment.connect.requested from the control panel.
    """

    try:
        if vault_data is None:
            log.error("[CONNECTOR] on_connect called without vault_data")
            return

        deployments = vault_data.get("deployments", {})

        if dep_id:
            deployment = deployments.get(dep_id)
            if not deployment:
                log.error(f"[CONNECTOR] Deployment {dep_id} not found in vault")
                return
            _connect_single(deployment, dep_id)
        else:
            for dep_id, deployment in deployments.items():
                _connect_single(deployment, dep_id)
    except Exception as e:
        emit_gui_exception_log("deployment_connector.on_connect", e)
        return {}



def _connect_single(deployment, dep_id):

    try:
        sessions = get_sessions()
        if not sessions:
            print("[ERROR] No global sessions instance")
            return

        session_id = str(uuid.uuid4())
        group = {
            "id": session_id,
            "name": deployment.get("name", dep_id),
            "proto": "deployment",
            "deployment_id": dep_id,
            "deployment": deployment
        }

        # Register in SessionManager
        ctx = sessions.create(group)
        print(f"[DEBUG] Deployment {dep_id} using session {session_id}")

        # Enhance ctx with a bus
        ctx.bus = SessionBus(session_id)

        # Wire ConnectorBus → SessionBus
        ConnectorBus.get(session_id).on("inbound.raw",
            lambda **kw: ctx.bus.emit("inbound.message", **kw))
        ConnectorBus.get(session_id).on("channel.status",
            lambda **kw: ctx.bus.emit("channel.status", **kw))

        print(f"[BRIDGE] ConnectorBus wired into SessionBus for {session_id}")

        # Launch connectors for each agent
        for agent in deployment.get("agents", []):
            adapter = AgentConnectionWrapper(agent, deployment)
            proto, host, port = adapter.proto, adapter.host, adapter.port
            connector_fn = CONNECTOR_MAP.get(proto)
            if connector_fn:
                threading.Thread(
                    target=connector_fn,
                    args=(host, port, agent, deployment, session_id),
                    daemon=True
                ).start()
                print(f"[CONNECT] Launched {proto} connector for {agent.get('universal_id')} on {host}:{port}")

        return ctx

    except Exception as e:
        emit_gui_exception_log("deployment_connector._connect_single", e)
        return {}

def destroy_session(session_id):
    """
    Tear down a session: close connectors, update bus, remove context.
    """
    ctx = get_sessions().get(session_id)
    if not ctx:
        print(f"[DESTROY] ❌ No session {session_id} found")
        return

    # Close all connectors
    for channel, conn in list(ctx.channels.items()):
        if hasattr(conn, "close"):
            try:
                conn.close(session_id=session_id, channel_name=channel)
                print(f"[DESTROY] Closed connector {channel}")
            except Exception as e:
                print(f"[DESTROY] Error closing {channel}: {e}")
        ctx.channels.pop(channel, None)
        ctx.status[channel] = "disconnected"

    # Remove from session manager
    get_sessions().remove(session_id)
    print(f"[DESTROY] Session {session_id} removed from SessionManager")