import time
class FeedFormatter:
    ICONS = {
        "replace": "✅",
        "delete": "☠️",
        "restart": "🔁",
        "warning": "⚠️",
        "alert": "🚨",
        "info": "📰",
    }

    COLORS = {
        "INFO": "green",
        "WARN": "orange",
        "ERROR": "red",
        "ALERT": "crimson",
    }

    @staticmethod
    def format(event=None, **kwargs) -> str:
        if event is None:
            event = {}
        event.update(kwargs)

        ts = event.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
        level = event.get("level", "INFO").upper()
        etype = event.get("event_type", "info").lower()
        icon = FeedFormatter.ICONS.get(etype, "❓")
        color = FeedFormatter.COLORS.get(level, "#222")

        agent = event.get("agent", "?")
        status = event.get("status", "n/a")
        trace = event.get("trace", "—")
        details = event.get("details", "")
        sha = event.get("sha")
        kill_list = event.get("kill_list")

        session_id = event.get("session_id", "n/a")
        deployment = event.get("deployment", "n/a")

        # Build message body
        parts = [
            f"[{ts}] [{level}] [{etype.upper()}] "
            f"(deployment={deployment}, session={session_id}) "
            f"{icon} {etype.capitalize()} Confirmed: {agent} [{status}]"
        ]
        if sha:
            parts.append(f"sha={sha}")
        if kill_list is not None:
            parts.append(f"kill_list={kill_list}")
        if details:
            parts.append(f":: {details}")
        if trace:
            parts.append(f"(trace={trace})")

        # Wrap with HTML span for color
        return f"<span style='color:{color};'>{' '.join(parts)}</span>"
