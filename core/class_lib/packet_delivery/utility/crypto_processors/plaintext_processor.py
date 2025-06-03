from core.class_lib.packet_delivery.interfaces.packet_processor import PacketProcessorBase
class PlaintextProcessor(PacketProcessorBase):
    def prepare_for_processing(self, file_data):
        return file_data