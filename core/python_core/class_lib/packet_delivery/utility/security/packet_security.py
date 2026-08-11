# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time

from Crypto.PublicKey import RSA

from core.python_core.utils.crypto_utils import encrypt_with_ephemeral_aes, sign_data


def _coerce_signing_key(signing_key_obj):
    if signing_key_obj is None:
        raise ValueError("signing_key_obj is required")

    if hasattr(signing_key_obj, "has_private"):
        return signing_key_obj

    if isinstance(signing_key_obj, str):
        return RSA.import_key(signing_key_obj.encode())

    if isinstance(signing_key_obj, bytes):
        return RSA.import_key(signing_key_obj)

    raise TypeError("signing_key_obj must be an RSA key object or PEM")


def secure_payload(
    payload: dict,
    peer_pub_key_pem,
    serial_num,
    signing_key_obj,
    logger=None,
    extra_fields=None,
):
    """
    Encrypt and sign a payload for direct transport.

    Returns the signed ciphertext wrapper only. This helper does not build a
    Packet object and does not resolve keys from deployment metadata.
    """
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    if not peer_pub_key_pem:
        raise ValueError("peer_pub_key_pem is required")
    if not serial_num:
        raise ValueError("serial_num is required")

    signing_key_obj = _coerce_signing_key(signing_key_obj)
    sealed = encrypt_with_ephemeral_aes(payload, peer_pub_key_pem)

    packet = {
        "serial": serial_num,
        "content": sealed,
        "timestamp": int(time.time()),
    }

    if extra_fields is not None:
        if not isinstance(extra_fields, dict):
            raise TypeError("extra_fields must be a dict")
        blocked = {"content", "sig"}
        overlap = blocked.intersection(extra_fields)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(f"extra_fields cannot override signed packet field(s): {names}")
        packet.update(extra_fields)

    packet["sig"] = sign_data(packet, signing_key_obj)

    if logger:
        logger("Packet encrypted. Ready for transport")

    return packet


def wrap_packet_securely(
    payload: dict,
    peer_pub_key_pem=None,
    serial_num=None,
    signing_key_obj=None,
    logger=None,
    extra_fields=None,
    **kwargs,
):
    """
    Backward-named entry point for the new transport contract.

    Explicit key material is now mandatory. Deployment lookup, Packet wrapping,
    _find_pubkey, and _find_privkey were intentionally removed.
    """
    if "deployment" in kwargs:
        raise TypeError(
            "deployment lookup was removed; pass peer_pub_key_pem, serial_num, and signing_key_obj"
        )

    peer_pub_key_pem = (
        peer_pub_key_pem
        or kwargs.pop("remote_pubkey", None)
        or kwargs.pop("remote_pubkey_pem", None)
        or kwargs.pop("peer_public_key", None)
    )
    serial_num = serial_num or kwargs.pop("serial", None) or kwargs.pop("serial_number", None)
    signing_key_obj = (
        signing_key_obj
        or kwargs.pop("signing_key", None)
        or kwargs.pop("signing_privkey_obj", None)
        or kwargs.pop("signing_privkey_pem", None)
    )
    extra_fields = extra_fields or kwargs.pop("metadata", None) or kwargs.pop("signed_fields", None)

    if kwargs:
        unknown = ", ".join(sorted(kwargs))
        raise TypeError(f"unsupported secure payload argument(s): {unknown}")

    return secure_payload(
        payload=payload,
        peer_pub_key_pem=peer_pub_key_pem,
        serial_num=serial_num,
        signing_key_obj=signing_key_obj,
        logger=logger,
        extra_fields=extra_fields,
    )