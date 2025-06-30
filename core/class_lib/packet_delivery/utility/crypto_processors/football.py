import json
import base64
import os
from core.class_lib.packet_delivery.utility.encryption.utility.sig_payload_json import SigPayloadJson
from core.class_lib.packet_delivery.utility.encryption.utility.interfaces.sig_payload import SigPayload
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA as CryptoRSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
from core.mixin.log_method import LogMixin
from core.class_lib.packet_delivery.utility.crypto_processors.identity import IdentityObject
from core.class_lib.packet_delivery.utility.crypto_processors.identity_manager import IdentityManager
from core.utils.crypto_utils import generate_aes_key
class Football(LogMixin):

    def __init__(self):

        #identity, includes pubkey, timestamp, universal_id
        self.identities = IdentityManager() # {"identity": identity, "priv": None, "pub": None, "agent": None, "verified": False}

        # Use Asymmetrix Encyption
        self._use_asymmetric_encryption = False

        # Use Symmetrix Encryption
        self._use_symmetric_encryption = True

        #Add the identity with the payload before encrypting
        self._use_payload_identity_file  = True

        #sign the payload {+ payload} with a private key : self._payload_signing_key
        self._sign_payload = True

        # verify the signed payload {+ payload} with matching pubkey : self._payload_verifying_key
        self._verify_signed_payload = True

        # used for signing a payload
        self._payload_signing_key = None

        # used for verifying a signed payload
        self._payload_verifying_key = None

        #cached identities of targets already sent to
        self.cached_keys: dict[str, str] = {}

        #if asymmetric_encryption is turned on this is the key used
        self.pubkey_for_encryption = None


        #used to encrypt the whole package, saved in a json structure
        #by default randomly generated, and encrypted using targets pubkey
        self.aes_key=generate_aes_key()

        #encrypt the target's aes key using its pubkey
        self._encrypt_aes_key_using_target_pubkey = True

        # decrypt the target's aes key using its privkey
        self._decrypt_aes_key_using_privkey = True

        #pubkey used to encrypt the aes key and encrypt the packet
        self._aes_encryption_pubkey = None

        #privkey used to decrypt the aes key then decrypt the packet
        self._aes_encryption_privkey = None

        #cache used to hold previously processed identities
        self.target_identity_cache={}

        #key to verify the identity, Matrix's pubkey
        self._identity_sig_verifier_pubkey = None

        #allowed list of agents that we can receive packets from
        self._allowed_sender_ids = set()

        #base path of agent's identity file
        self._identity_base_path = None

    def set_use_asymmetric_encryption(self, use_asymmetric_encryption:bool=True):
        self._use_asymmetric_encryption = bool(use_asymmetric_encryption)
        return self

    def set_identity_base_path(self, identity_base_path:str):
        self._identity_base_path = identity_base_path
        return self

    def use_asymmetric_encryption(self)->bool:
        return self._use_asymmetric_encryption

    def set_use_symmetric_encryption(self, use_symmetric_encryption:bool=True):
        self._use_symmetric_encryption = bool(use_symmetric_encryption)
        return self

    def use_symmetric_encryption(self)->bool:
        return self._use_symmetric_encryption

    def set_use_payload_identity_file(self, use_payload_identity_file):
        self._use_payload_identity_file  = bool(use_payload_identity_file)

    def use_payload_identity_file(self)->bool:
        return self._use_payload_identity_file

    # key to verify the identity of an agent, Matrix's pubkey
    def set_identity_sig_verifier_pubkey(self, identity_sig_verifier_pubkey):
        self._identity_sig_verifier_pubkey=identity_sig_verifier_pubkey

    #this is used for integrity checking, during packaging the packet, during encryption
    #the identity set as payload_identity is packed with the package
    #then signed
    def get_payload_identity(self):
        for key, identity_obj in self.identities.items():
            if identity_obj.is_payload_identity():
                return {"identity": identity_obj.get_identity(), "sig": identity_obj.get_identity_sig()}
        raise RuntimeError("[Football] No payload identity found in identity.")

    def set_sign_payload(self, sign_payload:bool=True):
        self._sign_payload = bool(sign_payload)
        return self

    def sign_payload(self)->bool:
        return self._sign_payload

    def set_verify_signed_payload(self, verify_signed_payload:bool=True):
        self._verify_signed_payload = bool(verify_signed_payload)
        return self

    def verify_signed_payload(self)->bool:
        return self._verify_signed_payload

    #used during sending a packet - signs the payload - if set
    def set_payload_signing_key(self, priv:str):
        self.set_sign_payload(True)
        try:
            CryptoRSA.import_key(priv)
            self._payload_signing_key = priv
        except Exception as e:
            self.log("Failed to set payload_siging_key", error=e, block="PERSONAL_IDENTITY", level="ERROR")

    #used during sending a packet - signs the payload - if set
    def get_payload_signing_key(self):
        return self._payload_signing_key

    #Noramlly 1 or 2 identities will be added. The first is the calling agent's identity(owner agent)
    #Second, will be the identity of the target agent, that you more than likely retrieved from the filesystem.
    #The first identity, if set, will be embedded with the payload and both are signed with private key to prove the sender
    def add_identity(self,
                     vault: dict,                               # a vault contains - privkey, identity{agent_name, pubkey, timestamp}
                     identity_name: str ="agent_owner",         # maintain named identities for organization
                     verify_keypair_match: bool = True,         # make sure the priv and pub are a pair
                     verify_universal_id:bool=True,             # does the identity agent_name match the sender universal_id
                     universal_id=None,                         # the name to match against the identity name
                     verify_sig:bool=True,                      # verify the identity against the matrix sig
                     sig_verifier_pubkey=None,                  # Matrix pubkey
                     is_payload_identity:bool=False,            # is this identity meant to be placed with payload; there can only be one per packet, the sender's identity
                     is_pubkey_for_encryption:bool=False,       # used to encrypt using the pubkey
                     is_privkey_for_signing:bool=False,         # Is priv key used to sign the subpacket
                     encrypt_aes_key_using_pub=False  # encrypt using a random aes key using the pubkey in the identity; aes key will be used to encrypt the packet
                     ):
        """
        Sets your agent's own identity and verifies:
        - That the identity is signed by Matrix (if verifier is set)
        - That the private key matches the public key in the identity
        Stores both for future signing.
        """
        private_key_pem = None
        id_obj = IdentityObject()

        try:

            verify_sig=bool(verify_sig)

            identity = vault.get("identity",{})

            sig = str(vault.get("sig", {}))
            sig.strip()

            if not identity or not sig:
                self.log("Missing identity or signature", block="FOOTBALL", level="ERROR")
                return False

            if not all(k in identity for k in ("universal_id", "pub", "timestamp")):
                raise ValueError("Malformed identity payload.")

            if verify_keypair_match:
                private_key_pem = vault.get("priv").strip()

                #pub_pem = identity["pub"].encode("utf-8")
                priv_key = CryptoRSA.import_key(private_key_pem)

                # Step 1: Verify that priv_key corresponds to pub_key in identity
                derived_pub = priv_key.publickey().export_key().decode().strip()
                if derived_pub != identity["pub"].strip():
                    raise ValueError("Private key does not match identity pubkey.")

            # Step 2: Verify the Matrix signature if sig_pubkey is set
            if verify_sig:
                sig_verifier_pubkey_pem = self._identity_sig_verifier_pubkey.encode("utf-8")
                spk=serialization.load_pem_public_key(
                    sig_verifier_pubkey_pem,
                    backend=default_backend()
                )
                sp = SigPayloadJson()
                sp.set_payload(identity)

                if not self.verify_sig(sp, spk, sig):
                    raise ValueError("Signature verification failed.")
                id_obj.set_priv(private_key_pem)

            if bool(verify_universal_id):
                universal_id.strip()
                if not universal_id:
                    raise ValueError("verify_agent is set, but no agent_name supplied.")
                if universal_id != identity["universal_id"].strip():
                    raise ValueError(f"Agent name mismatch agent_name: {universal_id}, identity: {identity['universal_id'].strip()}.")

            # Passed all checks — now store identity and key
            id_obj.set_identity(identity)
            id_obj.set_identity_sig(sig)
            id_obj.set_pub(identity["pub"])
            id_obj.set_universal_id(identity["universal_id"])
            id_obj.set_verified(True)
            id_obj.set_is_payload_identity(is_payload_identity)
            if verify_sig:
                id_obj.set_sig_verifier_pubkey(self._identity_sig_verifier_pubkey)

            self.identities.add(identity_name, id_obj)

            #used for both sending and receiving packets
            if is_pubkey_for_encryption:
                self.set_pubkey_for_encryption(identity["pub"])

            #used during sending packets, signing the subpacket
            if is_privkey_for_signing:
                self.set_payload_signing_key(private_key_pem)

            #if this identity is the identity of the target, then use the pubkey passed to encrypte the aes key
            if encrypt_aes_key_using_pub:
                self._aes_encryption_pubkey = identity["pub"]

            return True

        except Exception as e:
            self.identities.add(identity_name, id_obj)
            self.log(f"Failed to set personal identity {vault} for {universal_id}", error=e, block="PERSONAL_IDENTITY", level="ERROR")

    #pubkey used to encrypt the payload if asymmetric encryption is set self._use_asymmetric_encryption = True
    #   note: only for small packets
    def set_pubkey_for_encryption(self, pubkey:str):

        try:
            serialization.load_pem_public_key(pubkey.encode(), backend=default_backend())
            self.pubkey_for_encryption = pubkey
        except Exception as e:
            self.log(error=e, block="main_try")
        return self

    # pubkey used to encrypt the payload if asymmetric encryption is set self._use_asymmetric_encryption = True
    #   note: only for small packets
    def get_pubkey_for_encryption(self):
        return self.pubkey_for_encryption

    #pubkey that verifies a private key signature. used with a packet that
    #has been signed using privkey
    def set_pubkey_verifier(self, sig_verifier_pubkey):
        try:
            serialization.load_pem_public_key(sig_verifier_pubkey.encode(), backend=default_backend())
            self._payload_verifying_key = sig_verifier_pubkey
        except Exception as e:
            self.log(error=e, block="main_try")
        return self

    def get_pubkey_verifier(self):
        return self._payload_verifying_key

    def set_identity_cache(self, identity_cache:dict):
        self.target_identity_cache=identity_cache
        return self

    #idenity = includes pubkey, uuid that owns it, time
    # this would be someone the agent would want to send a packet to
    # he would load the identity file the retrieve the signed_public_key.json file, which contains
    # the receivers pubkey, signed by Matrix
    def load_identity_file(self,
                     vault: dict=None,
                     identity_base_path: str="",
                     codex: str="codex",
                     universal_id: str="",
                     sig_verifier_pubkey: str=None,
                     identity_name: str = "target_identity",
                     encrypt_aes_key_using_pub:bool=True  #encrypt using a random aes key using the pubkey in the identity; aes key will be used to encrypt the packet
                     ):

        try:

            universal_id.strip().lower()
            if universal_id =="":
                raise ValueError("Missing universal_id.")

            #if a vault was passed don't bother hitting the filesystem
            if not isinstance(vault, dict):
                identity_base_path = identity_base_path or self._identity_base_path
                if not identity_base_path:
                    raise ValueError("Missing identity base path: both identity_base_path and self._identity_base_path are undefined.")

                full_path=os.path.join(identity_base_path, universal_id, codex,"signed_public_key.json")
                with open(full_path, "r") as f:
                    vault = json.load(f)

            self.add_identity(vault,
                              identity_name=identity_name,
                              verify_keypair_match=False,
                              verify_universal_id=True,
                              universal_id=universal_id,
                              verify_sig=True,
                              sig_verifier_pubkey=sig_verifier_pubkey, #Matrix Key
                              encrypt_aes_key_using_pub=encrypt_aes_key_using_pub
                              )

            r = True

        except Exception as e:
            self.log(error=e, block="main_try")
            r = False

        return r

    #Used internally to the class to verify the Matrix sig on the indentity
    def verify_sig(self, payload: SigPayload, sig_pubkey, signature_b64: str) -> bool:
        try:
            if not sig_pubkey:
                raise ValueError("Verifier key not set")

            # Convert cryptography public key to PEM format, then to pycryptodome RSA key
            pem_bytes = sig_pubkey.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            rsa_key = CryptoRSA.import_key(pem_bytes)

            signature = base64.b64decode(signature_b64)
            payload_bytes = payload.get_payload()
            digest = SHA256.new(payload_bytes)

            pkcs1_15.new(rsa_key).verify(digest, signature)

            self.log("Signature verified successfully", block="BL_VERIFY", level="INFO")

            return True

        except Exception as e:
            self.log("Signature verification failed", error=e, block="BL_VERIFY", level="ERROR")
            return False

    #this is the private_key used if self._use_symmetric_encryption = True
    def set_aes_key(self, aes_key):
        try:
            self.aes_key = aes_key
        except Exception as e:
            raise RuntimeError(f"Failed to set identity: {e}") from e

    #this is the private_key returned if self._use_symmetric_encryption = True
    def get_aes_key(self):
        return self.aes_key

    def set_encrypt_aes_key_using_target_pubkey(self, encrypt_aes_key_using_target_pubkey=True):
        self._encrypt_aes_key_using_target_pubkey = bool(encrypt_aes_key_using_target_pubkey)

    #if True, encrypt the aes key, using the users pubkey as a field in the PacketCryptoMixin.encrypt_packet() packet
    def encrypt_aes_key_using_target_pubkey(self):
        return self._encrypt_aes_key_using_target_pubkey

    def set_decrypt_aes_key_using_privkey(self, decrypt_aes_key_using_privkey=True):
        self._decrypt_aes_key_using_privkey= bool(decrypt_aes_key_using_privkey)

    #if True, decrypt the aes key, using the users privkey
    def decrypt_aes_key_using_privkey(self):
        return self._decrypt_aes_key_using_privkey

    #when the target agent's identity is loaded, the pubkey embedded will be used
    def set_aes_encryption_pubkey(self, pubkey):
        self._aes_encryption_pubkey = pubkey

    #privkey to decrypt the aes key used to decrypt the payload
    def set_aes_encryption_privkey(self, privkey):
        self._aes_encryption_privkey = privkey

    #pubkey to encrypt the aes key used to encrypt the payload
    def get_aes_encryption_pubkey(self):
        return self._aes_encryption_pubkey

    def get_aes_encryption_privkey(self):
        return self._aes_encryption_privkey

    def set_allowed_sender_ids(self, allowed_ids: list[str]):
        """
        Sets a list of allowed sender universal_ids for downstream enforcement.
        """
        if isinstance(allowed_ids, list):
            self._allowed_sender_ids = set(allowed_ids)
        else:
            self._allowed_sender_ids = set()
        return self

    # allowed list of agents that we can receive packets from
    def get_allowed_sender_ids(self)->set:
        return self._allowed_sender_ids
