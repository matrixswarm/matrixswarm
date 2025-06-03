from core.class_lib.packet_delivery.interfaces.packet_processor import PacketProcessorBase
from core.class_lib.packet_delivery.utility.encryption.packet_crypto_mixin import PacketCryptoMixin

class PacketDecryptor(PacketProcessorBase):
    def __init__(self, key: bytes, pub_key = None):
        self.key = key
        self.pub_key = pub_key

    def prepare_for_processing(self, file_data):
        return PacketCryptoMixin().decrypt_packet(file_data, self.key, pub_key=self.pub_key)