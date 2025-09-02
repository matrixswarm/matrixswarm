from matrix_gui.core.event_bus import EventBus
from .connector.https.https import HTTPSConnector
from .connector.wss.wss import WSSConnector
from .entity.adapter.agent_connection_wrapper import AgentConnectionWrapper
from matrix_gui.config.boot.globals import get_sessions
import threading

import uuid
import logging


# later: from discord_connector import connect_discord, etc.

log = logging.getLogger("deployment_connector")

# Map proto → connector function
CONNECTOR_MAP = {
    "https": HTTPSConnector(),
    "wss": WSSConnector(),
    # future: "discord": connect_discord,
    # future: "telegram": connect_telegram,
    # future: "slack": connect_slack,
    # future: "sms": connect_sms,
}


def on_connect(dep_id=None, vault_data=None, **kwargs):
    """
    Handles deployment.connect.requested from the control panel.
    """

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

SUPPORTED_PROTOS = {"https", "wss"}

def _connect_single(deployment, dep_id):
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
        "deployment": deployment  # embed whole dict here
    }
    get_sessions().create(group)
    print(f"[DEBUG] Deployment {dep_id} using session {session_id}")


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
def initialize():

    EventBus.on("deployment.connect.requested", on_connect)
    print("[CONNECTOR] Deployment connector online")
