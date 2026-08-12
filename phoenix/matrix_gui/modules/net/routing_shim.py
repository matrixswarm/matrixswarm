# routing_shim.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse

@dataclass
class RouteSpec:
    """Describe how to reach the target."""
    mode: str                  # 'direct' | 'vpn' | 'tor' | 'http' | 'socks5' | 'chain'
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None
    vpn_id: Optional[str] = None
    chain: Optional[List['RouteSpec']] = None

def parse_route(s: str) -> RouteSpec:
    """
    Accepts:
      'direct'
      'vpn:edge01'
      'tor'                       (assumes local tor SOCKS at 127.0.0.1:9050)
      'http://host:8080'          (HTTP proxy)
      'socks5://user:pass@h:1080' (SOCKS5 proxy)
      'chain(http://a:8080,socks5://b:1080,tor)'
    """
    s = (s or "direct").strip()
    if s == "direct": return RouteSpec(mode="direct")
    if s.startswith("vpn:"): return RouteSpec(mode="vpn", vpn_id=s.split(":",1)[1])

    if s == "tor": return RouteSpec(mode="socks5", host="127.0.0.1", port=9050)

    if s.startswith("chain(") and s.endswith(")"):
        inner = s[len("chain("):-1]
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        return RouteSpec(mode="chain", chain=[parse_route(p) for p in parts])

    if s.startswith("http://") or s.startswith("https://") or s.startswith("socks5://"):
        u = urlparse(s)
        user = u.username or None
        pwd = u.password or None
        host = u.hostname
        port = u.port
        mode = "http" if u.scheme.startswith("http") else "socks5"
        return RouteSpec(mode=mode, host=host, port=port, user=user, password=pwd)

    # default fallback
    return RouteSpec(mode="direct")

def _flatten_chain(rs: RouteSpec) -> List[RouteSpec]:
    if rs.mode != "chain": return [rs]
    out = []
    for hop in (rs.chain or []):
        out.extend(_flatten_chain(hop))
    return out

def build_requests_proxies(route: RouteSpec) -> Optional[Dict[str, str]]:
    """Return a requests-compatible proxies dict or None."""
    # VPN is OS-level => noop here, still tag for UI
    hops = _flatten_chain(route)
    if not hops or hops[0].mode == "direct": return None

    # choose the LAST hop as outward proxy (simple, robust)
    last = hops[-1]
    if last.mode == "http":
        auth = f"{last.user}:{last.password}@" if last.user else ""
        url = f"http://{auth}{last.host}:{last.port}"
        return {"http": url, "https": url}
    if last.mode == "socks5":
        auth = f"{last.user}:{last.password}@" if last.user else ""
        url = f"socks5h://{auth}{last.host}:{last.port}"
        return {"http": url, "https": url}
    return None

def build_ws_proxy_kwargs(route: RouteSpec) -> Dict:
    """
    Return kwargs for websocket-client:
      http_proxy_host, http_proxy_port, http_proxy_auth, proxy_type ('http'|'socks5')
    """
    hops = _flatten_chain(route)
    if not hops or hops[0].mode == "direct": return {}
    last = hops[-1]
    if last.mode in ("http", "socks5"):
        kw = {
            "http_proxy_host": last.host,
            "http_proxy_port": last.port,
            "proxy_type": "http" if last.mode == "http" else "socks5",
        }
        if last.user:
            kw["http_proxy_auth"] = (last.user, last.password or "")
        return kw
    return {}
