"""Read-only Bitcoin mainnet address statistics from Esplora."""
from __future__ import annotations

import re
import requests
from urllib.parse import urlsplit


ADDRESS_RE = re.compile(r"^(?:[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[ac-hj-np-z02-9]{11,87})$")
DEFAULT_API = "https://blockstream.info/api"


def validate_api_url(value):
    url = str(value).strip().rstrip("/")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Bitcoin explorer must be an HTTPS Esplora API URL")
    return url


def validate_address(address):
    address = str(address).strip()
    if not ADDRESS_RE.fullmatch(address):
        raise ValueError("Enter a Bitcoin mainnet public address (1…, 3…, or bc1…)")
    return address


def parse_address_stats(data, address):
    if not isinstance(data, dict) or data.get("address") != address:
        raise ValueError("Explorer returned a different address")
    result = {}
    for source, prefix in (("chain_stats", "confirmed"), ("mempool_stats", "pending")):
        stats = data.get(source)
        if not isinstance(stats, dict):
            raise ValueError("Explorer response has no address statistics")
        for name in ("funded_txo_sum", "spent_txo_sum", "tx_count"):
            value = stats.get(name)
            if type(value) is not int or value < 0:
                raise ValueError("Explorer returned invalid Bitcoin amounts")
        result[prefix + "_sats"] = stats["funded_txo_sum"] - stats["spent_txo_sum"]
        result[prefix + "_tx_count"] = stats["tx_count"]
    if result["confirmed_sats"] < 0:
        raise ValueError("Explorer returned a negative confirmed balance")
    return result


def fetch_address(address, api_url=DEFAULT_API):
    address = validate_address(address)
    url = validate_api_url(api_url) + "/address/" + address
    with requests.get(url, timeout=(5, 10), stream=True,
                      allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Explorer did not return address statistics")
        chunks, size = [], 0
        for chunk in response.iter_content(8192):
            size += len(chunk)
            if size > 65536:
                raise ValueError("Explorer response is too large")
            chunks.append(chunk)
        import json
        return parse_address_stats(json.loads(b"".join(chunks)), address)
