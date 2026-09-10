"""Pure parsing and classification helpers for Site Sentinel."""

from __future__ import annotations

import ipaddress
import json
import re
from collections import Counter, defaultdict
from typing import Iterable, Mapping


_COMBINED_LOG_RE = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[[^]]+\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)(?:\s+[^\"]+)?"\s+'
    r'(?P<status>\d{3})\s+\S+'
    r'(?:\s+"[^"]*"\s+"(?P<user_agent>[^"]*)")?'
    r'(?:\s+"(?P<forwarded_ip>[^"]*)")?'
)
_BOT_RE = re.compile(
    r"bot|spider|crawler|scrapy|curl|wget|python-requests|go-http-client|headless",
    re.IGNORECASE,
)


def _valid_ip(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def parse_access_line(line: str, *, prefer_forwarded_ip: bool = True) -> dict | None:
    """Parse common/combined or JSON web access logs without trusting log text."""
    line = line.strip()
    if not line:
        return None

    if line.startswith("{"):
        try:
            payload = json.loads(line)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, Mapping):
            return None
        forwarded = (
            payload.get("cf_connecting_ip")
            or payload.get("http_cf_connecting_ip")
            or payload.get("x_forwarded_for")
        )
        direct = (
            payload.get("client_ip")
            or payload.get("remote_addr")
            or payload.get("remote_ip")
        )
        ip = _valid_ip(forwarded if prefer_forwarded_ip else direct)
        ip = ip or _valid_ip(direct) or _valid_ip(forwarded)
        path = payload.get("request_uri") or payload.get("path") or payload.get("url")
        status = payload.get("status") or payload.get("status_code")
        try:
            status = int(status)
        except (TypeError, ValueError):
            return None
        if not ip or not isinstance(path, str):
            return None
        return {
            "ip": ip,
            "method": str(payload.get("request_method") or payload.get("method") or "GET"),
            "path": path[:2048],
            "status": status,
            "user_agent": str(payload.get("http_user_agent") or payload.get("user_agent") or "")[:512],
        }

    match = _COMBINED_LOG_RE.match(line)
    if not match:
        return None
    fields = match.groupdict()
    direct = _valid_ip(fields.get("ip"))
    forwarded = _valid_ip(fields.get("forwarded_ip"))
    ip = (forwarded if prefer_forwarded_ip else direct) or direct or forwarded
    if not ip:
        return None
    return {
        "ip": ip,
        "method": fields["method"],
        "path": fields["path"][:2048],
        "status": int(fields["status"]),
        "user_agent": (fields.get("user_agent") or "")[:512],
    }


def summarize_traffic(
    events: Iterable[Mapping],
    *,
    window_sec: int,
    top_n: int,
    ignored_ips: set[str] | None = None,
    per_ip_warning_rpm: float = 120,
    per_ip_critical_rpm: float = 300,
    total_warning_rpm: float = 600,
    total_critical_rpm: float = 1500,
    unique_path_warning: int = 80,
    error_ratio_warning: float = 0.35,
) -> dict:
    """Summarize request pressure and identify likely aggressive clients."""
    ignored = ignored_ips or set()
    requests_by_ip = Counter()
    errors_by_ip = Counter()
    paths_by_ip: dict[str, set[str]] = defaultdict(set)
    bot_hits_by_ip = Counter()

    for event in events:
        ip = event.get("ip")
        if not isinstance(ip, str) or ip in ignored:
            continue
        requests_by_ip[ip] += 1
        paths_by_ip[ip].add(str(event.get("path", "")))
        try:
            if int(event.get("status", 0)) >= 400:
                errors_by_ip[ip] += 1
        except (TypeError, ValueError):
            pass
        if _BOT_RE.search(str(event.get("user_agent", ""))):
            bot_hits_by_ip[ip] += 1

    minutes = max(float(window_sec) / 60.0, 1.0 / 60.0)
    total_requests = sum(requests_by_ip.values())
    total_rpm = total_requests / minutes
    severity = "INFO"
    reasons: list[str] = []
    if total_rpm >= total_critical_rpm:
        severity = "CRITICAL"
        reasons.append(f"total request rate {total_rpm:.1f} rpm")
    elif total_rpm >= total_warning_rpm:
        severity = "WARNING"
        reasons.append(f"total request rate {total_rpm:.1f} rpm")

    top_ips = []
    for ip, count in requests_by_ip.most_common(max(1, top_n)):
        rpm = count / minutes
        error_ratio = errors_by_ip[ip] / count if count else 0.0
        unique_paths = len(paths_by_ip[ip])
        bot_ratio = bot_hits_by_ip[ip] / count if count else 0.0
        aggressive = (
            rpm >= per_ip_warning_rpm
            and (
                unique_paths >= unique_path_warning
                or error_ratio >= error_ratio_warning
                or bot_ratio >= 0.5
            )
        )
        if rpm >= per_ip_critical_rpm:
            severity = "CRITICAL"
            reasons.append(f"{ip} generated {rpm:.1f} rpm")
        elif aggressive and severity == "INFO":
            severity = "WARNING"
            reasons.append(f"aggressive crawler pattern from {ip}")
        top_ips.append({
            "ip": ip,
            "requests": count,
            "rpm": round(rpm, 1),
            "unique_paths": unique_paths,
            "error_ratio": round(error_ratio, 3),
            "bot_ratio": round(bot_ratio, 3),
            "aggressive": aggressive,
        })

    return {
        "severity": severity,
        "reasons": list(dict.fromkeys(reasons)),
        "window_sec": window_sec,
        "total_requests": total_requests,
        "total_rpm": round(total_rpm, 1),
        "top_ips": top_ips,
    }


def classify_target(public: Mapping, origin: Mapping | None = None) -> tuple[str, str]:
    """Classify public/origin evidence without treating one edge miss as downtime."""
    if public.get("transport_ok") and not public.get("content_ok", True):
        return "CRITICAL", "PUBLIC_CONTENT_MISMATCH"
    if public.get("transport_ok") and not public.get("assets_ok", True):
        return "WARNING", "PUBLIC_ASSET_FAILURE"
    if public.get("ok"):
        if origin is not None and not origin.get("ok"):
            return "WARNING", "ORIGIN_DEGRADED"
        if public.get("latency_warning"):
            return "WARNING", "PUBLIC_LATENCY"
        return "INFO", "HEALTHY"
    if origin is not None and origin.get("ok"):
        return "WARNING", "EDGE_DEGRADED"
    return "CRITICAL", "SITE_UNAVAILABLE"
