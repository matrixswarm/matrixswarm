# Authored by Daniel F MacDonald and ChatGPT aka The Generals
"""Read-only website integrity, load, and aggressive-client monitor."""

from __future__ import annotations

import os
import socket
import ssl
import sys
import time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import psutil
import requests

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.utils.swarm_sleep import interruptible_sleep
from site_sentinel.analysis import classify_target, parse_access_line, summarize_traffic


class _AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        candidate = None
        if tag in {"script", "img"}:
            candidate = values.get("src")
        elif tag == "link" and "stylesheet" in values.get("rel", "").lower():
            candidate = values.get("href")
        if candidate:
            self.assets.append(candidate)


def _public_url(value: str) -> str:
    """Remove credentials, query strings, and fragments from evidence."""
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path or "/", "", ""))
    except Exception:
        return "invalid-url"


class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        cfg = self.tree_node.get("config", {}) or {}
        self.name = "SiteSentinel"
        self.targets = [item for item in cfg.get("targets", []) if isinstance(item, dict)]
        self.interval = max(5, int(cfg.get("interval_sec", 30)))
        self.timeout = max(1, int(cfg.get("request_timeout_sec", 8)))
        self.failure_threshold = max(1, int(cfg.get("failure_threshold", 3)))
        self.recovery_threshold = max(1, int(cfg.get("recovery_threshold", 2)))
        self.latency_warning_ms = max(1, int(cfg.get("latency_warning_ms", 2500)))
        self.tls_warning_days = max(1, int(cfg.get("tls_warning_days", 21)))
        self.check_assets = bool(cfg.get("check_assets", True))
        self.max_assets = max(0, min(25, int(cfg.get("max_assets", 8))))
        self.report_role = cfg.get("report_to_role", "hive.forensics.data_feed")
        self.log_every = max(self.interval, int(cfg.get("log_every", 300)))

        traffic = cfg.get("traffic", {}) or {}
        self.traffic_enabled = bool(traffic.get("enabled", True))
        self.access_logs = [str(path) for path in traffic.get("access_logs", []) if path]
        self.traffic_window = max(10, int(traffic.get("window_sec", 60)))
        self.top_n_ips = max(1, min(50, int(traffic.get("top_n_ips", 10))))
        self.ignored_ips = {str(ip) for ip in traffic.get("ignored_ips", [])}
        self.prefer_forwarded_ip = bool(traffic.get("prefer_forwarded_ip", True))
        self.per_ip_warning_rpm = float(traffic.get("per_ip_warning_rpm", 120))
        self.per_ip_critical_rpm = float(traffic.get("per_ip_critical_rpm", 300))
        self.total_warning_rpm = float(traffic.get("total_warning_rpm", 600))
        self.total_critical_rpm = float(traffic.get("total_critical_rpm", 1500))
        self.unique_path_warning = int(traffic.get("unique_path_warning", 80))
        self.error_ratio_warning = float(traffic.get("error_ratio_warning", 0.35))

        load = cfg.get("load", {}) or {}
        self.cpu_warning_pct = float(load.get("cpu_warning_pct", 80))
        self.cpu_critical_pct = float(load.get("cpu_critical_pct", 95))
        self.memory_warning_pct = float(load.get("memory_warning_pct", 90))
        self.memory_critical_pct = float(load.get("memory_critical_pct", 97))
        self.load_warning_per_cpu = float(load.get("load_warning_per_cpu", 1.5))
        self.load_critical_per_cpu = float(load.get("load_critical_per_cpu", 3.0))

        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "MatrixSwarm-SiteSentinel/1.0"})
        self._condition_state: dict[str, dict] = {}
        self._log_offsets: dict[str, tuple[int, int]] = {}
        self._traffic_events: deque[dict] = deque()
        self._warned_missing_logs = False
        self._last_summary = 0.0
        self._emit_beacon = self.check_for_thread_poke(
            "worker", timeout=self.interval * 6, emit_to_file_interval=10
        )
        self.log(
            f"[SITE-SENTINEL] Online: {len(self.targets)} target(s), "
            f"interval={self.interval}s, confirm={self.failure_threshold} cycles, "
            "recovery is observation-only."
        )

    def worker(self, config=None, identity: IdentityObject = None):
        if not self.running:
            return
        try:
            self._emit_beacon()
            observations = [self._check_target(target) for target in self.targets]
            traffic = self._collect_traffic()
            pressure = self._system_pressure(traffic)

            for observation in observations:
                key = f"site:{observation['url']}"
                self._evaluate_condition(
                    key,
                    observation["severity"],
                    observation["reason"],
                    observation,
                )
            self._evaluate_condition(
                "site:traffic-pressure",
                pressure["severity"],
                pressure["reason"],
                pressure,
            )

            now = time.time()
            if now - self._last_summary >= self.log_every:
                self._last_summary = now
                healthy = sum(item["severity"] == "INFO" for item in observations)
                top = traffic.get("top_ips", [])[:3]
                top_text = ", ".join(
                    f"{item['ip']}={item['rpm']:.1f}rpm" for item in top
                ) or "none"
                self.log(
                    f"[SITE-SENTINEL][SUMMARY] healthy={healthy}/{len(observations)} "
                    f"load={pressure['load_1m']:.2f} cpu={pressure['cpu_pct']:.1f}% "
                    f"traffic={traffic.get('total_rpm', 0):.1f}rpm top={top_text}"
                )
        except Exception as exc:
            self.log("[SITE-SENTINEL] Monitoring cycle failed", error=exc, level="ERROR")
        interruptible_sleep(self, self.interval)

    def _check_target(self, target: dict) -> dict:
        url = str(target.get("url", "")).strip()
        origin_url = str(target.get("origin_url", "")).strip()
        expect = str(target.get("expect", "")).strip()
        host_header = str(target.get("host_header", "")).strip()
        public = self._probe(url, expect=expect, check_assets=self.check_assets)
        origin = None
        if origin_url:
            origin_host = host_header or (urlsplit(url).hostname or "")
            origin = self._probe(
                origin_url,
                expect=expect,
                headers={"Host": origin_host} if origin_host else None,
                check_assets=False,
            )
        severity, reason = classify_target(public, origin)
        tls_days = self._tls_days_remaining(url)
        if tls_days is not None and tls_days <= self.tls_warning_days and severity == "INFO":
            severity, reason = "WARNING", "TLS_EXPIRING"
        return {
            "url": _public_url(url),
            "note": str(target.get("note", ""))[:200],
            "severity": severity,
            "reason": reason,
            "public": public,
            "origin": origin,
            "tls_days_remaining": tls_days,
        }

    def _probe(self, url, *, expect="", headers=None, check_assets=False):
        result = {
            "url": _public_url(url), "ok": False, "transport_ok": False,
            "content_ok": True, "assets_ok": True, "status": "ERR",
            "elapsed_ms": 0, "latency_warning": False, "failed_assets": [],
        }
        if urlsplit(url).scheme not in {"http", "https"}:
            result["error"] = "URL must use http or https"
            return result
        started = time.monotonic()
        try:
            response = self._session.get(
                url, timeout=self.timeout, allow_redirects=True, headers=headers
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            result.update({
                "status": response.status_code,
                "elapsed_ms": elapsed_ms,
                "transport_ok": 200 <= response.status_code < 400,
                "latency_warning": elapsed_ms >= self.latency_warning_ms,
                "server": str(response.headers.get("server", ""))[:100],
                "cloudflare_ray": str(response.headers.get("cf-ray", ""))[:100],
            })
            body = response.text[:2_000_000]
            if expect:
                result["content_ok"] = expect.casefold() in body.casefold()
            if check_assets and result["transport_ok"] and self.max_assets:
                failed = self._check_page_assets(response.url, body, headers)
                result["failed_assets"] = failed
                result["assets_ok"] = not failed
            result["ok"] = (
                result["transport_ok"]
                and result["content_ok"]
                and result["assets_ok"]
            )
        except requests.RequestException as exc:
            result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            result["error"] = type(exc).__name__
        return result

    def _check_page_assets(self, base_url, body, headers):
        parser = _AssetParser()
        try:
            parser.feed(body)
        except Exception:
            return ["html-parse-error"]
        failed = []
        seen = set()
        for reference in parser.assets:
            asset_url = urljoin(base_url, reference)
            if asset_url in seen or urlsplit(asset_url).scheme not in {"http", "https"}:
                continue
            seen.add(asset_url)
            try:
                with self._session.get(
                    asset_url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    headers=headers,
                    stream=True,
                ) as response:
                    if response.status_code >= 400:
                        failed.append(f"{_public_url(asset_url)} [{response.status_code}]")
            except requests.RequestException as exc:
                failed.append(f"{_public_url(asset_url)} [{type(exc).__name__}]")
            if len(seen) >= self.max_assets:
                break
        return failed[: self.max_assets]

    def _tls_days_remaining(self, url):
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            return None
        try:
            context = ssl.create_default_context()
            with socket.create_connection(
                (parts.hostname, parts.port or 443), timeout=self.timeout
            ) as raw:
                with context.wrap_socket(raw, server_hostname=parts.hostname) as wrapped:
                    expires = ssl.cert_time_to_seconds(wrapped.getpeercert()["notAfter"])
            return round((expires - time.time()) / 86400.0, 1)
        except Exception:
            return None

    def _collect_traffic(self):
        if not self.traffic_enabled:
            return {"severity": "INFO", "reasons": [], "total_rpm": 0, "top_ips": []}
        now = time.time()
        found_log = False
        for raw_path in self.access_logs:
            path = Path(raw_path)
            try:
                stat = path.stat()
            except OSError:
                continue
            found_log = True
            inode = int(getattr(stat, "st_ino", 0))
            prior = self._log_offsets.get(raw_path)
            if prior is None:
                self._log_offsets[raw_path] = (inode, stat.st_size)
                continue
            old_inode, offset = prior
            if old_inode != inode or stat.st_size < offset:
                offset = 0
            try:
                with path.open("r", encoding="utf-8", errors="replace") as stream:
                    stream.seek(offset)
                    for line in stream:
                        parsed = parse_access_line(
                            line, prefer_forwarded_ip=self.prefer_forwarded_ip
                        )
                        if parsed:
                            parsed["ts"] = now
                            self._traffic_events.append(parsed)
                    self._log_offsets[raw_path] = (inode, stream.tell())
            except OSError:
                continue
        if not found_log and not self._warned_missing_logs:
            self._warned_missing_logs = True
            self.log(
                "[SITE-SENTINEL][TRAFFIC] No configured access log is readable; "
                "request/IP analysis is idle.",
                level="WARNING",
            )
        cutoff = now - self.traffic_window
        while self._traffic_events and self._traffic_events[0]["ts"] < cutoff:
            self._traffic_events.popleft()
        return summarize_traffic(
            self._traffic_events,
            window_sec=self.traffic_window,
            top_n=self.top_n_ips,
            ignored_ips=self.ignored_ips,
            per_ip_warning_rpm=self.per_ip_warning_rpm,
            per_ip_critical_rpm=self.per_ip_critical_rpm,
            total_warning_rpm=self.total_warning_rpm,
            total_critical_rpm=self.total_critical_rpm,
            unique_path_warning=self.unique_path_warning,
            error_ratio_warning=self.error_ratio_warning,
        )

    def _system_pressure(self, traffic):
        cpu_pct = float(psutil.cpu_percent(interval=None))
        memory_pct = float(psutil.virtual_memory().percent)
        load_1m = float(os.getloadavg()[0]) if hasattr(os, "getloadavg") else 0.0
        cpu_count = max(1, psutil.cpu_count() or 1)
        load_per_cpu = load_1m / cpu_count
        severity = traffic.get("severity", "INFO")
        reasons = list(traffic.get("reasons", []))
        if (
            cpu_pct >= self.cpu_critical_pct
            or memory_pct >= self.memory_critical_pct
            or load_per_cpu >= self.load_critical_per_cpu
        ):
            severity = "CRITICAL"
            reasons.append(
                f"critical server pressure CPU={cpu_pct:.1f}% "
                f"memory={memory_pct:.1f}% load/core={load_per_cpu:.2f}"
            )
        elif (
            cpu_pct >= self.cpu_warning_pct
            or memory_pct >= self.memory_warning_pct
            or load_per_cpu >= self.load_warning_per_cpu
        ) and severity == "INFO":
            severity = "WARNING"
            reasons.append(
                f"server pressure CPU={cpu_pct:.1f}% memory={memory_pct:.1f}% "
                f"load/core={load_per_cpu:.2f}"
            )
        return {
            "severity": severity,
            "reason": "; ".join(reasons) or "NORMAL_LOAD",
            "cpu_pct": round(cpu_pct, 1),
            "memory_pct": round(memory_pct, 1),
            "load_1m": round(load_1m, 2),
            "load_per_cpu": round(load_per_cpu, 2),
            "traffic": traffic,
        }

    def _evaluate_condition(self, key, severity, reason, metrics):
        issue = severity in {"WARNING", "CRITICAL"}
        state = self._condition_state.setdefault(
            key, {"active": False, "failures": 0, "recoveries": 0, "severity": "INFO"}
        )
        if issue:
            state["failures"] += 1
            state["recoveries"] = 0
            if state["failures"] < self.failure_threshold:
                self.log(
                    f"[SITE-SENTINEL][VERIFY] {key} {reason} "
                    f"({state['failures']}/{self.failure_threshold})",
                    level="WARNING",
                )
                return
            if not state["active"] or state["severity"] != severity:
                state["active"] = True
                state["severity"] = severity
                self.log(
                    f"[SITE-SENTINEL][{severity}] {key}: {reason}",
                    level="CRITICAL" if severity == "CRITICAL" else "WARNING",
                )
                self._send_status(key, reason, severity, metrics, status=reason)
            return

        state["failures"] = 0
        if not state["active"]:
            return
        state["recoveries"] += 1
        if state["recoveries"] >= self.recovery_threshold:
            old_severity = state["severity"]
            state.update({"active": False, "recoveries": 0, "severity": "INFO"})
            self.log(f"[SITE-SENTINEL][RECOVERY] {key} recovered from {old_severity}.")
            self._send_status(key, "Health checks recovered.", "INFO", metrics, status="RECOVERED")

    def _send_status(self, service, details, severity, metrics, status="ISSUE"):
        endpoints = self.get_nodes_by_role(self.report_role)
        if not endpoints:
            self.log(
                f"[SITE-SENTINEL] No forensic endpoint for role={self.report_role}",
                level="ERROR",
            )
            return
        report_metrics = dict(metrics)
        report_metrics["condition"] = service
        inner = self.get_delivery_packet("standard.status.event.packet")
        inner.set_data({
            "source_agent": self.command_line_args.get("universal_id", "site-sentinel"),
            "service_name": "site_sentinel",
            "status": status,
            "severity": severity,
            "details": details,
            "metrics": report_metrics,
        })
        outer = self.get_delivery_packet("standard.command.packet")
        outer.set_packet(inner, "content")
        for endpoint in endpoints:
            outer.set_payload_item("handler", endpoint.get_handler())
            self.pass_packet(outer, endpoint.get_universal_id())


if __name__ == "__main__":
    Agent().boot()
