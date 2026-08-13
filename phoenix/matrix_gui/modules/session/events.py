
# Central event names used by SessionManager / Dispatcher / WS client

EVT_SESSION_OPEN      = "session.open"          # {tab_id, https_cfg, ws_cfg}
EVT_SESSION_CLOSED    = "session.closed"        # {session_id}
EVT_OUTBOUND_MESSAGE  = "outbound.message"      # {session_id, channel, handler, content}
EVT_INBOUND_MESSAGE   = "inbound.message"       # {session_id, channel, source, payload, ts}
EVT_CONN_STATUS       = "connection.status"     # {session_id, channel, status, info}
