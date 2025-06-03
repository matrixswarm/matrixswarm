from core.class_lib.packet_delivery.utility.encryption.packet_crypto_mixin import PacketCryptoMixin
from core.class_lib.packet_delivery.interfaces.packet_processor import PacketEncryptorBase

class PacketEncryptor(PacketEncryptorBase):
    def __init__(self, key: bytes, priv_key=None):
        self.key = key
        self.priv_key = priv_key

    def prepare_for_delivery(self, packet_obj):
        return PacketCryptoMixin().encrypt_packet(packet_obj, self.key, priv_key=self.priv_key)