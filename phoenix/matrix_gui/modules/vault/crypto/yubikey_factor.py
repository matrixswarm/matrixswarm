"""YubiKey-backed credential derivation for Phoenix vaults.

Phoenix never reads or stores the HMAC secret.  A preconfigured YubiKey OTP
slot answers a deterministic challenge derived from the operator's secondary
word, and the response is converted into the password consumed by the existing
vault KDF.
"""

from __future__ import annotations

import base64
import hashlib
import unicodedata
from dataclasses import dataclass
from threading import Event
from typing import Callable


DEFAULT_YUBIKEY_SLOT = 2
_CHALLENGE_DOMAIN = b"matrixswarm.phoenix.vault.yubikey.challenge.v1\x00"
_PASSWORD_DOMAIN = b"matrixswarm.phoenix.vault.yubikey.password.v1\x00"
_HMAC_SHA1_RESPONSE_SIZE = 20


class YubiKeyFactorError(RuntimeError):
    """A safe, user-displayable YubiKey failure."""


@dataclass(frozen=True)
class YubiKeyCredential:
    password: str
    serial: int | None


def normalize_secondary_word(secondary_word: str) -> str:
    """Return the stable, case-sensitive word representation used by Phoenix."""
    if not isinstance(secondary_word, str):
        raise TypeError("Secondary word must be text.")
    normalized = unicodedata.normalize("NFC", secondary_word.strip())
    if not normalized:
        raise ValueError("Secondary word cannot be empty.")
    return normalized


def build_yubikey_challenge(secondary_word: str) -> bytes:
    """Build the fixed 64-byte HMAC-SHA1 challenge accepted by all slot modes."""
    normalized = normalize_secondary_word(secondary_word)
    return hashlib.sha512(
        _CHALLENGE_DOMAIN + normalized.encode("utf-8")
    ).digest()


def derive_vault_password(secondary_word: str, response: bytes) -> str:
    """Convert a YubiKey response and word into a 256-bit vault credential."""
    normalized = normalize_secondary_word(secondary_word)
    if not isinstance(response, bytes) or len(response) != _HMAC_SHA1_RESPONSE_SIZE:
        raise ValueError("YubiKey returned an invalid HMAC-SHA1 response.")

    digest = hashlib.sha256(
        _PASSWORD_DOMAIN
        + response
        + b"\x00"
        + normalized.encode("utf-8")
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def request_yubikey_credential(
    secondary_word: str,
    *,
    slot: int = DEFAULT_YUBIKEY_SLOT,
    cancellation_event: Event | None = None,
    touch_callback: Callable[[], None] | None = None,
) -> YubiKeyCredential:
    """Request an HMAC-SHA1 response from one attached YubiKey over USB.

    The slot is read-only here. Phoenix deliberately never provisions or
    rewrites YubiKey configuration because doing so could destroy an existing
    credential.
    """
    challenge = build_yubikey_challenge(secondary_word)

    try:
        from ykman.device import list_all_devices
        from yubikit.core.otp import OtpConnection
        from yubikit.yubiotp import SLOT, YubiOtpSession
    except ImportError as exc:
        raise YubiKeyFactorError(
            "YubiKey support is not installed. Install Phoenix requirements "
            "and restart the cockpit."
        ) from exc

    try:
        devices = list_all_devices([OtpConnection])
    except Exception as exc:
        raise YubiKeyFactorError(
            "Phoenix could not access the YubiKey OTP interface."
        ) from exc

    if not devices:
        raise YubiKeyFactorError(
            "No USB YubiKey with an enabled OTP interface was found."
        )
    if len(devices) > 1:
        raise YubiKeyFactorError(
            "More than one YubiKey is connected. Leave only the vault key attached."
        )

    try:
        yubikey_slot = SLOT(slot)
    except ValueError as exc:
        raise YubiKeyFactorError("Phoenix supports YubiKey slot 1 or 2.") from exc

    device, info = devices[0]
    event = cancellation_event or Event()
    touch_announced = False

    def on_keepalive(status):
        nonlocal touch_announced
        # The YubiKey OTP protocol uses keepalive status 2 for waiting on touch.
        if status == 2 and not touch_announced and touch_callback:
            touch_announced = True
            touch_callback()

    try:
        with device.open_connection(OtpConnection) as connection:
            session = YubiOtpSession(connection)
            if not session.get_config_state().is_configured(yubikey_slot):
                raise YubiKeyFactorError(
                    f"YubiKey slot {slot} is empty. Configure it for "
                    "HMAC-SHA1 challenge-response with touch required."
                )
            response = session.calculate_hmac_sha1(
                yubikey_slot,
                challenge,
                event,
                on_keepalive,
            )
    except YubiKeyFactorError:
        raise
    except Exception as exc:
        if event.is_set():
            raise YubiKeyFactorError("YubiKey request was cancelled.") from exc
        raise YubiKeyFactorError(
            f"YubiKey slot {slot} did not complete HMAC-SHA1 "
            "challenge-response."
        ) from exc

    return YubiKeyCredential(
        password=derive_vault_password(secondary_word, response),
        serial=getattr(info, "serial", None),
    )
