"""Validation helpers for Railgun's remote-host clock prerequisite."""


MAX_CLOCK_SKEW_SECONDS = 120
_SYNCHRONIZED_STATES = {"1", "true", "yes"}


def validate_remote_clock(
    response,
    controller_epoch,
    max_skew_seconds=MAX_CLOCK_SKEW_SECONDS,
):
    """Return ``(remote_iso, skew_seconds)`` or reject an unsafe clock."""
    fields = str(response or "").strip().split("|", 2)
    if len(fields) != 3:
        raise ValueError("Remote clock check returned malformed data.")

    remote_epoch_text, sync_state, remote_iso = fields
    try:
        remote_epoch = int(remote_epoch_text)
    except (TypeError, ValueError) as exc:
        raise ValueError("Remote clock check returned an invalid epoch.") from exc

    if sync_state.strip().lower() not in _SYNCHRONIZED_STATES:
        raise ValueError(
            "Remote host is not synchronized with an NTP source."
        )

    skew_seconds = round(abs(float(controller_epoch) - remote_epoch))
    if skew_seconds > max_skew_seconds:
        raise ValueError(
            f"Controller/host clock skew is {skew_seconds}s; "
            f"maximum allowed is {max_skew_seconds}s."
        )

    if not remote_iso:
        raise ValueError("Remote clock check returned no UTC timestamp.")
    return remote_iso, skew_seconds
