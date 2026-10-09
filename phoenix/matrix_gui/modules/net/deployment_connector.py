# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from .class_lib.processes.connection_launcher import ConnectionLauncher
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from .entity.adapter.agent_connection_wrapper import AgentConnectionWrapper
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.dispatcher.session_bus import SessionBus
from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.modules.net.connector.interfaces.connector_spec import ConnectorSpec, ConnectorPolicy
from matrix_gui.modules.net.primary_ingress import select_primary_ingress

# Supported connector types for outbound/inbound agent protocols
SUPPORTED_PROTOS = {"https", "wss", "smtp", "ssh", "imap", "ssh_egress"}
PERSISTENT_PROTOS = {"wss", "imap", "ssh_egress"}   # loop connectors
EPHEMERAL_PROTOS  = {"https", "smtp"} # one-shot connectors (adjust if smtp becomes loop)

# Mapping of protocol type → full class path of connector implementation
CONNECTOR_MAP = {
    "https": "matrix_gui.modules.net.connector.egress.https.https.HTTPSConnector",
    "wss": "matrix_gui.modules.net.connector.ingress.wss.wss.WSSConnector",
    "smtp": "matrix_gui.modules.net.connector.egress.smtp.smtp.SMTPConnector",
    "ssh": "matrix_gui.modules.net.connector.egress.ssh.SSHConnector",
    "ssh_egress": "matrix_gui.modules.net.connector.ingress.ssh.SSHIngressConnector",
    "imap": "matrix_gui.modules.net.connector.ingress.imap.imap.IMAPIngressConnector",
    # Future connector types (examples):
    # "discord": connect_discord,
    # "telegram": connect_telegram,
    # "slack": connect_slack,
    # "sms": connect_sms,
}


def _transport_policy(proto, connection):
    """Return (persistent, requires_packet) for one connector record."""
    if proto == "ssh":
        mode = str((connection or {}).get("ssh_mode") or "one_shot").strip().lower()
        if mode not in {"one_shot", "persistent"}:
            raise ValueError("SSH delivery mode must be one_shot or persistent")
        persistent = mode == "persistent"
        return persistent, not persistent
    persistent = proto in PERSISTENT_PROTOS
    return persistent, proto in EPHEMERAL_PROTOS

def _connect_single(deployment, session_id, dep_id, *, managed_startup=False):
    """
    Create a SessionContext and register + launch connector threads for a deployment.

    Design rules:
      - Outgoing connectors (outgoing.command) launch immediately.
      - Ingress connectors (payload.reception) launch ONLY if they are the *selected primary ingress*.
        All other ingress connectors are registered but held until the Multiplexer activates them.
      - If multiple agents are marked default_payload_reception, we don't block deployment:
        we pick the last one in deployment order, matching the session and Routes UI.
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
        ctx.failures = {}   # Fixed transport codes observed during startup.

        ctx.bus = SessionBus(session_id)
        ctx._bus_refs = []  # track bus bindings for cleanup

        def inbound_proxy(**kw):
            ctx.bus.emit("inbound.message", **kw)

        def status_proxy(**kw):
            # Retain status even if a parent-owned listener subscribes just
            # after connector startup; this is observation, not authorization.
            ctx.status[kw.get("channel")] = kw.get("status")
            ctx.bus.emit("channel.status", **kw)

        def delivery_proxy(**kw):
            ctx.bus.emit("channel.delivery", **kw)

        def failure_proxy(**kw):
            ctx.failures[kw.get("channel")] = kw.get("error_code")
            ctx.bus.emit("channel.failure", **kw)

        ConnectorBus.get(session_id).on("inbound.raw", inbound_proxy)
        ConnectorBus.get(session_id).on("channel.status", status_proxy)
        ConnectorBus.get(session_id).on("channel.delivery", delivery_proxy)
        ConnectorBus.get(session_id).on("channel.failure", failure_proxy)

        ctx._bus_refs.extend([
            ("inbound.raw", inbound_proxy),
            ("channel.status", status_proxy),
            ("channel.delivery", delivery_proxy),
            ("channel.failure", failure_proxy),
        ])

        print(f"[BRIDGE] ConnectorBus wired into SessionBus for {session_id}")

        # ---------------------------------------------------------
        # Startup, the dispatcher and Routes must select the same receiver.
        # Otherwise the displayed route can remain dormant until Apply is clicked.
        # ---------------------------------------------------------
        primary_ingress = select_primary_ingress(deployment)
        primary_ingress_uid = primary_ingress.get("universal_id") if primary_ingress else None

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


            persistent, requires_packet = _transport_policy(proto, conn)
            should_monitor = persistent

            # ingress: only keep the chosen one alive
            if is_ingress:
                should_monitor = persistent and is_primary_ingress

            # Context passed into connector instance via shared state
            context = {
                "agent": agent,
                "deployment": deployment,
                "session_id": session_id,
                # Optional: can be used by launch gating if you implement auto_launch
                # "auto_launch": should_monitor,
            }

            # --- policy: monitor/autostart/packet gating ---
            monitor = should_monitor and not managed_startup
            auto_start = not managed_startup and ((is_ingress and is_primary_ingress and monitor) or (is_egress and monitor))

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
        if not managed_startup:
            launcher.start_monitor()
        return ctx

    except Exception as e:
        emit_gui_exception_log("deployment_connector._connect_single", e)
        return {}
