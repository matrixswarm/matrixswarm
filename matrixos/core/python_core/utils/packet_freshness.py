"""Stateless freshness checks for timestamps covered by packet signatures.

Receivers must authenticate the timestamp and optional expiry before dispatch.
No packet hashes, database, or receiver-start cutoff are maintained here.
"""
import math
import time


def packet_is_fresh(timestamp, *, window=314, expires=None, now=None):
    """Accept a signed packet within its validity period and clock-skew window."""
    def finite_number(value):
        return type(value) in (int, float) and math.isfinite(value)

    try:
        now = time.time() if now is None else now
        if not all(finite_number(value) for value in (timestamp, now, window)):
            return False
        if timestamp < 0 or now < 0 or window <= 0 or timestamp > now + window:
            return False
        deadline = timestamp + window
        if expires is not None:
            if not finite_number(expires) or expires < timestamp:
                return False
            deadline = expires
        return now <= deadline
    except (ValueError, TypeError, OverflowError):
        return False
