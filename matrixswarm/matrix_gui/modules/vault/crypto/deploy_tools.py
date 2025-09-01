import os
import json
import base64
import hashlib
from Crypto.PublicKey import RSA
from matrix_gui.modules.vault.crypto.cert_utils import set_hash_bang, embed_agent_sources
from Crypto.Cipher import AES

def get_random_aes_key(length=32):
    return os.urandom(length)

def encrypt_data(data_bytes, key):
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(data_bytes)
    return {
        "nonce": base64.b64encode(nonce).decode(),
        "tag": base64.b64encode(tag).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode()
    }

def embed_keypair_if_marker(obj, universal_id=None):
    if isinstance(obj, dict):
        this_id = obj.get("universal_id", universal_id)
        for k, v in list(obj.items()):
            if k == "privkey" and v == "##GENERATE_KEY##":
                key = RSA.generate(2048)
                obj[k] = key.export_key().decode()
                obj["pubkey"] = key.publickey().export_key().decode()
            else:
                embed_keypair_if_marker(v, this_id)
    elif isinstance(obj, list):
        for item in obj:
            embed_keypair_if_marker(item, universal_id)

def generate_swarm_encrypted_directive(directive, clown_car=True, hashbang=True, base_path = None):

    try:

        base_path = base_path or os.getcwd()

        if clown_car:
            embed_agent_sources(directive, base_path=base_path)
        if hashbang:
            set_hash_bang(directive, base_path=base_path)

        data_bytes = json.dumps(directive, indent=2).encode()

        aes_key = get_random_aes_key()
        encrypted_bundle = encrypt_data(data_bytes, aes_key)
        directive_hash = hashlib.sha256(data_bytes).hexdigest()

        return encrypted_bundle, aes_key, directive_hash

    except Exception as e:
        print(str(e))

    return False

def decrypt_swarm_encrypted_directive(encrypted_bundle: dict, swarm_key_b64: str) -> dict:
    """
    Decrypts an encrypted swarm directive JSON using the provided swarm_key (base64-encoded).

    :param encrypted_bundle: Dict loaded from encrypted .json directive file.
    :param swarm_key_b64: Base64-encoded AES swarm key.
    :return: Decrypted directive as Python dictionary.
    """
    # Decode swarm key from base64
    swarm_key = base64.urlsafe_b64decode(swarm_key_b64)

    # Extract encrypted data from bundle
    ciphertext = base64.urlsafe_b64decode(encrypted_bundle["ciphertext"])
    nonce = base64.urlsafe_b64decode(encrypted_bundle["nonce"])
    tag = base64.urlsafe_b64decode(encrypted_bundle["tag"])

    # Decrypt using AES-GCM
    cipher = AES.new(swarm_key, AES.MODE_GCM, nonce=nonce)
    decrypted_data = cipher.decrypt_and_verify(ciphertext, tag)

    # Load decrypted directive JSON into Python dictionary
    directive = json.loads(decrypted_data.decode("utf-8"))

    return directive


def write_encrypted_bundle_to_file(bundle, path):
    with open(path, "w") as f:
        json.dump(bundle, f, indent=2)
    return path