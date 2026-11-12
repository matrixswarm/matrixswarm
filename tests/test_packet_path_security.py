"""Packet transport stays within its opened channel and rejects unsafe names."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.class_lib.packet_delivery.delivery_agent.file.json_file import delivery_agent as delivery
from core.python_core.class_lib.packet_delivery.reception_agent.file.json_file import reception_agent as reception


class Packet:
    def __init__(self, value=None):
        self.value = value
    def get_packet(self):
        return self.value
    def set_data(self, value):
        self.value = value


class Crypto:
    def set_logger(self, *_):
        pass
    def prepare_for_delivery(self, packet):
        return packet.get_packet()
    def prepare_for_processing(self, value):
        return value


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux openat2 required")
class PacketPathSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "packets"
        self.root.mkdir()
        self.outside = self.base / "outside"
        self.outside.mkdir()

    def sender(self, uid="agent", zone="incoming"):
        return (delivery.DeliveryAgent().set_location({"path": str(self.root)})
                .set_address([uid]).set_drop_zone({"drop": zone})
                .set_packet(Packet({"message": "hello"})).set_crypto_handler(Crypto()))

    def receiver(self):
        return (reception.ReceptionAgent().set_location({"path": str(self.root)})
                .set_address(["agent"]).set_drop_zone({"drop": "incoming"})
                .set_packet(Packet()).set_crypto_handler(Crypto()))

    def test_packet_roundtrip_and_explicit_filename(self):
        sender = self.sender().set_identifier("message")
        sender.deliver()
        self.assertEqual(sender.get_error_success(), 0, sender.get_error_success_msg())
        result = self.receiver().set_identifier("message").receive()
        self.assertEqual(result.value, {"message": "hello"})
        self.assertEqual(Path(sender.get_saved_filename()).name, "message.json")

    def test_atomic_replace_keeps_packets_private(self):
        incoming = self.root / "agent/incoming"
        incoming.mkdir(parents=True)
        packet = incoming / "message.json"
        packet.write_text("old")
        packet.chmod(0o644)
        sender = self.sender().set_identifier("message")
        sender.deliver()
        self.assertEqual(sender.get_error_success(), 0, sender.get_error_success_msg())
        self.assertEqual(packet.stat().st_mode & 0o777, 0o600)

    def test_traversal_and_symlinked_recipient_are_refused(self):
        for bad in ("../outside", "/tmp/escape", "bad\\name"):
            with self.subTest(bad=bad):
                sender = self.sender(uid=bad)
                sender.deliver()
                self.assertNotEqual(sender.get_error_success(), 0)
                with self.assertRaises(ValueError):
                    self.sender().set_identifier(bad)
        (self.root / "agent").symlink_to(self.outside, target_is_directory=True)
        sender = self.sender().set_identifier("test")
        sender.deliver()
        self.assertNotEqual(sender.get_error_success(), 0)
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_symlinked_packet_is_not_read_and_hardlinked_target_not_overwritten(self):
        incoming = self.root / "agent/incoming"
        incoming.mkdir(parents=True)
        target = self.outside / "secret"
        target.write_text('{"message":"outside"}')
        (incoming / "symlink.json").symlink_to(target)
        self.assertIsNone(self.receiver().set_identifier("symlink").receive())
        os.link(target, incoming / "hardlink.json")
        sender = self.sender().set_identifier("hardlink")
        sender.deliver()
        self.assertNotEqual(sender.get_error_success(), 0)
        self.assertEqual(target.read_text(), '{"message":"outside"}')

    def test_unsafe_packet_does_not_block_later_valid_packet(self):
        incoming = self.root / "agent/incoming"
        incoming.mkdir(parents=True)
        target = self.outside / "secret"
        target.write_text('{"message":"outside"}')
        (incoming / "bad.json").symlink_to(target)
        (incoming / "good.json").write_text('{"message":"inside"}')
        with patch.object(reception.os, "listdir", return_value=["bad.json", "good.json"]):
            self.assertEqual(self.receiver().receive().value, {"message": "inside"})

    def test_delivery_directory_swap_cannot_redirect_write(self):
        incoming = self.root / "agent/incoming"
        incoming.mkdir(parents=True)
        moved = self.root / "agent/moved"
        original_write = delivery.write_file_at
        def swap(fd, name, payload, **kwargs):
            incoming.rename(moved)
            incoming.symlink_to(self.outside, target_is_directory=True)
            return original_write(fd, name, payload, **kwargs)
        with patch.object(delivery, "write_file_at", side_effect=swap):
            sender = self.sender().set_identifier("message")
            sender.deliver()
        self.assertEqual(sender.get_error_success(), 0, sender.get_error_success_msg())
        self.assertEqual(json.loads((moved / "message.json").read_text()), {"message": "hello"})
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_runtime_comm_symlink_is_rejected(self):
        comm = self.base / "universes/runtime/golden/20261112_120000/comm"
        comm.parent.mkdir(parents=True)
        comm.symlink_to(self.outside, target_is_directory=True)
        sender = (delivery.DeliveryAgent().set_location({"path": str(comm)})
                  .set_address(["agent"]).set_drop_zone({"drop": "incoming"})
                  .set_packet(Packet({"message": "hello"})).set_crypto_handler(Crypto()))
        sender.deliver()
        self.assertNotEqual(sender.get_error_success(), 0)
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_pinned_receiver_survives_zone_swap(self):
        incoming = self.root / "agent/incoming"
        incoming.mkdir(parents=True)
        (incoming / "message.json").write_text('{"message":"inside"}')
        (self.outside / "message.json").write_text('{"message":"outside"}')
        fd = os.open(incoming, os.O_RDONLY | os.O_DIRECTORY)
        receiver = self.receiver().set_identifier("message").set_directory_fd(fd)
        os.close(fd)
        self.addCleanup(receiver.close)
        incoming.rename(self.root / "agent/moved")
        incoming.symlink_to(self.outside, target_is_directory=True)
        self.assertEqual(receiver.receive().value, {"message": "inside"})

    def test_pinned_sender_survives_root_swap(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        sender = self.sender().set_identifier("message").set_location_fd(fd)
        os.close(fd)
        self.addCleanup(sender.close)
        moved = self.base / "moved-root"
        self.root.rename(moved)
        self.root.symlink_to(self.outside, target_is_directory=True)
        sender.deliver()
        self.assertEqual(sender.get_error_success(), 0, sender.get_error_success_msg())
        self.assertEqual(json.loads((moved / "agent/incoming/message.json").read_text()), {"message": "hello"})
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_changing_receiver_location_discards_old_zone_pin(self):
        incoming = self.root / "agent/incoming"
        incoming.mkdir(parents=True)
        (incoming / "message.json").write_text('{"message":"old"}')
        new_zone = self.outside / "agent/incoming"
        new_zone.mkdir(parents=True)
        (new_zone / "message.json").write_text('{"message":"new"}')
        fd = os.open(incoming, os.O_RDONLY | os.O_DIRECTORY)
        receiver = self.receiver().set_identifier("message").set_directory_fd(fd)
        os.close(fd)
        self.addCleanup(receiver.close)
        receiver.set_location({"path": str(self.outside)})
        self.assertEqual(receiver.receive().value, {"message": "new"})


if __name__ == "__main__":
    unittest.main()
