"""Forensic interpretation of Site Sentinel evidence."""


class Investigator:
    def __init__(self, agent_ref, service_name, all_events):
        self.agent = agent_ref
        self.service_name = service_name
        self.all_events = all_events

    def add_specific_findings(self, findings):
        self.agent.log("Running SITE-SENTINEL-specific forensic checks")
        event = next(
            (
                item for item in reversed(self.all_events)
                if item.get("service_name") == "site_sentinel"
                and str(item.get("severity", "")).upper() == "CRITICAL"
            ),
            {},
        )
        status = str(event.get("status", "UNKNOWN"))
        metrics = event.get("metrics", {}) or {}
        if status == "PUBLIC_CONTENT_MISMATCH":
            summary = (
                "Public page content failed its required marker check. The site may "
                "be serving an error template, stale cache, or incomplete deployment."
            )
        elif status == "SITE_UNAVAILABLE":
            summary = (
                "Both public and origin evidence indicate unavailability; this is "
                "unlikely to be a single transient CDN edge failure."
            )
        else:
            summary = f"Site Sentinel confirmed a critical condition: {status}."

        traffic = metrics.get("traffic", {}) or {}
        top_ips = traffic.get("top_ips", []) or []
        if top_ips:
            leaders = ", ".join(
                f"{item.get('ip')} ({item.get('rpm', 0)} rpm, "
                f"{item.get('unique_paths', 0)} paths, "
                f"errors={float(item.get('error_ratio', 0)):.0%})"
                for item in top_ips[:5]
            )
            summary += f"\nTop request sources: {leaders}."
        if metrics.get("cpu_pct") is not None:
            summary += (
                f"\nServer pressure: CPU={metrics.get('cpu_pct')}%, "
                f"memory={metrics.get('memory_pct')}%, "
                f"load/core={metrics.get('load_per_cpu')}."
            )
        findings.insert(0, f"**Concise Analysis:**\n---\n{summary}\n---")
        return findings
