# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time, json
from Crypto.PublicKey import RSA
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.utils.crypto_utils import encrypt_with_ephemeral_aes, sign_data
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

def wrap_packet_securely(inner_data, deployment, sign=False, encrypt=False, target_uid="matrix"):
    if not (sign or encrypt):
        # fallback passthrough
        pk = Packet()
        pk.set_data(inner_data)
        return pk

    # Get encryption and signing keys
    remote_pubkey = _find_pubkey(deployment, target_uid)
    signer_privkey = _find_privkey(deployment, target_uid)

    # Build sealed (JSON string of inner payload)
    sealed_data = json.dumps(inner_data, separators=(",", ":"))

    # Encrypt if needed
    if encrypt:
        if not remote_pubkey:
            raise ValueError("Missing remote_pubkey for encryption")
        sealed_data = encrypt_with_ephemeral_aes(json.loads(sealed_data), remote_pubkey)

    # Now sign the outer shell
    packet_content = {
        "content": sealed_data,
        "timestamp": int(time.time())
    }

    if sign:
        if not signer_privkey:
            raise ValueError("Missing signing key for GUI")
        signer_privkey_obj = RSA.import_key(signer_privkey.encode() if isinstance(signer_privkey, str) else signer_privkey)
        sig = sign_data(packet_content, signer_privkey_obj)
        packet_content["sig"] = sig

    # Final wrapper packet
    wrapper = Packet()
    wrapper.set_data({
        "timestamp": packet_content["timestamp"],
        "content": packet_content
    })
    return wrapper


def _find_pubkey(deployment, uid):
    """
    Returns the signing public key for the given agent UID from the vault_data.
    Expects vault_data structured as:
    {
        "<deployment_id>": {
            "label": "matrix",
            "certs": {
                "matrix": {
                    "signing": {
                        "pub": "..."
                    }
                }
            }
        }
    }
    """
    try:

        return deployment.get('certs',{}).get(uid,{}).get("signing", {}).get("pubkey")
    except Exception as e:
        emit_gui_exception_log("wrap_packet_securely._find_pubkey", e)
    return None

def _find_privkey(deployment, uid):
    """
    Searches the vault_data for the private signing key of the given agent UID.

    Expects vault_data structure like:
    {
        "<deployment_id>": {
            "certs": {
                "<uid>": {
                    "signing": {
                        "priv": "-----BEGIN PRIVATE KEY-----..."
                    }
                }
            }
        }
    }

    Returns:
        str or None: the PEM string of the private key, or None if not found.
    """
    try:

        return deployment.get('certs',{}).get(uid,{}).get("signing", {}).get("remote_privkey")
    except Exception as e:
        emit_gui_exception_log("wrap_packet_securely._find_privkey", e)
    return None

