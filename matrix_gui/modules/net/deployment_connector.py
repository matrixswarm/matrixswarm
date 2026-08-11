# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from .class_lib.processes.connection_launcher import ConnectionLauncher
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from .entity.adapter.agent_connection_wrapper import AgentConnectionWrapper
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.dispatcher.session_bus import SessionBus
from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.modules.net.connector.interfaces.connector_spec import ConnectorSpec, ConnectorPolicy

# Supported connector types for outbound/inbound agent protocols
SUPPORTED_PROTOS = {"https", "wss", "smtp"}
PERSISTENT_PROTOS = {"wss", "imap"}   # loop connectors
EPHEMERAL_PROTOS  = {"https", "smtp"} # one-shot connectors (adjust if smtp becomes loop)

# Mapping of protocol type → full class path of connector implementation
CONNECTOR_MAP = {
    "https": "matrix_gui.modules.net.connector.egress.https.https.HTTPSConnector",
    "wss": "matrix_gui.modules.net.connector.ingress.wss.wss.WSSConnector",
    "smtp": "matrix_gui.modules.net.connector.egress.smtp.smtp.SMTPConnector",
    "imap": "matrix_gui.modules.net.connector.ingress.imap.imap.IMAPIngressConnector",
    # Future connector types (examples):
    # "discord": connect_discord,
    # "telegram": connect_telegram,
    # "slack": connect_slack,
    # "sms": connect_sms,
}

def _connect_single(deployment, session_id, dep_id):
    """
    Create a SessionContext and register + launch connector threads for a deployment.

    Design rules:
      - Outgoing connectors (outgoing.command) launch immediately.
      - Ingress connectors (payload.reception) launch ONLY if they are the *selected primary ingress*.
        All other ingress connectors are registered but held until the Multiplexer activates them.
      - If multiple agents are marked default_payload_reception, we don't block deployment:
        we deterministically pick the *first* one encountered (deployment order).
    """
    try:
        sessions = get_sessions()
        if not sessions:
            print("[ERROR] No global sessions instance")
            return

        launcher = ConnectionLauncher()

        group = {
            "id": session_id,
            "name": deployment.get("name", dep_id),
            "proto": "deployment",
            "deployment_id": dep_id,
            "deployment": deployment,
            "connection_launcher": launcher,
        }

        # -----------------------------
        # SessionContext + bus wiring
        # -----------------------------
        ctx = sessions.create(group)
        ctx.channels = {}   # channel_uid -> agent dict (metadata)
        ctx.status = {}     # channel_uid -> status string (optional)

        ctx.bus = SessionBus(session_id)
        ctx._bus_refs = []  # track bus bindings for cleanup

        def inbound_proxy(**kw):
            ctx.bus.emit("inbound.message", **kw)

        def status_proxy(**kw):
            ctx.bus.emit("channel.status", **kw)

        ConnectorBus.get(session_id).on("inbound.raw", inbound_proxy)
        ConnectorBus.get(session_id).on("channel.status", status_proxy)

        ctx._bus_refs.extend([
            ("inbound.raw", inbound_proxy),
            ("channel.status", status_proxy),
        ])

        print(f"[BRIDGE] ConnectorBus wired into SessionBus for {session_id}")

        # ---------------------------------------------------------
        # Choose PRIMARY ingress deterministically.
        # If multiple defaults are flagged, "first wins" by deployment order.
        # ---------------------------------------------------------
        primary_ingress_uid = None

        # Pass 1: pick the first agent flagged default_payload_reception
        for agent in deployment.get("agents", []):
            conn = (agent.get("connection") or {})
            channel = (conn.get("channel") or "").strip().lower()
            if channel == "payload.reception" and bool(conn.get("default_payload_reception")):
                primary_ingress_uid = agent.get("universal_id")
                break

        # Pass 2: if none flagged, prefer websocket/wss ingress
        if not primary_ingress_uid:
            incoming = []
            for agent in deployment.get("agents", []):
                conn = (agent.get("connection") or {})
                if (conn.get("channel") or "").strip().lower() == "payload.reception":
                    incoming.append(agent)

            # Prefer wss / websocket by proto or name
            for agent in incoming:
                proto = ((agent.get("connection") or {}).get("proto") or "").strip().lower()
                name = (agent.get("name") or "").strip().lower()
                if proto == "wss" or "websocket" in name:
                    primary_ingress_uid = agent.get("universal_id")
                    break

            # Final fallback: first payload.reception in deployment order
            if not primary_ingress_uid and incoming:
                primary_ingress_uid = incoming[0].get("universal_id")

        # ---------------------------------------------------------
        # Register connectors. Launch only what should be live at boot.
        # NOTE: launcher.load() expects registry key = universal_id.
        # ---------------------------------------------------------
        for agent in deployment.get("agents", []):
            uid = agent.get("universal_id")
            if not uid:
                continue

            # Expose agent metadata in ctx for UI/debug (not the thread object)
            ctx.channels[uid] = agent

            # Resolve connector implementation from directive proto
            adapter = AgentConnectionWrapper(agent, deployment)
            proto = adapter.proto
            connector_class_path = CONNECTOR_MAP.get(proto)
            if not connector_class_path:
                continue

            conn = (agent.get("connection") or {})
            channel = (conn.get("channel") or "").strip().lower()

            is_ingress = (channel == "payload.reception")
            is_egress  = (channel == "outgoing.command")
            is_primary_ingress = (uid == primary_ingress_uid)


            should_monitor = proto in PERSISTENT_PROTOS

            # ingress: only keep the chosen one alive
            if is_ingress:
                should_monitor = (proto in PERSISTENT_PROTOS) and is_primary_ingress

            # Context passed into connector instance via shared state
            context = {
                "agent": agent,
                "deployment": deployment,
                "session_id": session_id,
                # Optional: can be used by launch gating if you implement auto_launch
                # "auto_launch": should_monitor,
            }

            # --- policy: monitor/autostart/packet gating ---
            requires_packet = (proto in EPHEMERAL_PROTOS)  # https/smtp one-shot
            monitor = should_monitor  # only loop connectors we want alive
            auto_start = (is_ingress and is_primary_ingress and monitor) or (is_egress and monitor)

            policy = ConnectorPolicy(
                auto_start=auto_start,
                monitor=monitor,
                requires_packet=requires_packet,
                ready=True,  # optional: you can compute readiness here (host/port present etc.)
                reason=(
                    "primary ingress" if (is_ingress and is_primary_ingress) else
                    "egress" if is_egress else
                    "dormant ingress"
                )
            )

            spec = ConnectorSpec(
                uid=uid,
                class_path=connector_class_path,
                context=context,
                policy=policy
            )

            launcher.load_spec(spec)

            # -----------------------------
            # Launch policy
            # -----------------------------
            # Only starts if policy allows; ephemerals won't start without packet
            launcher.launch(uid)

        # Start watchdog after registration/initial launches are complete
        launcher.start_monitor()
        return ctx

    except Exception as e:
        emit_gui_exception_log("deployment_connector._connect_single", e)
        return {}