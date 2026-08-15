import base64
import hashlib
import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / "matrixos/agents/python_core/email_send/email_send.py"
EDITOR_PATH = (
    ROOT
    / "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/email_send.py"
)
META_PATH = ROOT / "phoenix/agents_meta/email_send.json"


class _Queue:
    def __init__(self):
        self.items = []

    def enqueue(self, item):
        self.items.append(item)


class _BootAgent:
    pass


class _Identity:
    pass


def _install_module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module


def _load_agent_module():
    os.environ.setdefault("SITE_ROOT", str(ROOT))
    os.environ.setdefault("AGENT_PATH", str(ROOT / "matrixos/agents/python_core"))

    _install_module(
        "agents.python_core.email_send.factory.email_queue_manager",
        EmailQueueManager=object,
    )
    _install_module("core.python_core.boot_agent", BootAgent=_BootAgent)
    _install_module(
        "core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity",
        IdentityObject=_Identity,
    )
    _install_module(
        "core.python_core.class_lib.packet_delivery.utility.security.packet_security",
        wrap_packet_securely=lambda *args, **kwargs: None,
    )
    _install_module(
        "core.python_core.class_lib.processes.thread_launcher",
        ThreadLauncher=object,
    )
    _install_module(
        "core.python_core.utils.crypto_utils",
        pem_fix=lambda value: value,
    )
    rsa = types.SimpleNamespace(import_key=lambda value: value)
    _install_module("Crypto")
    _install_module("Crypto.PublicKey", RSA=rsa)

    name = "email_send_alert_encryption_under_test"
    spec = importlib.util.spec_from_file_location(name, AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class EmailAlertEncryptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_agent_module()

    def _agent(self, encrypt_alerts):
        agent = self.module.Agent.__new__(self.module.Agent)
        agent.queue = _Queue()
        agent.smtp_server = "mail.example.test"
        agent.smtp_port = 587
        agent.from_address = "alerts@example.test"
        agent.to_address = "operator@example.test"
        agent.password = "not-a-real-secret"
        agent.encryption = "STARTTLS"
        agent.encrypt_alerts = encrypt_alerts
        agent._peer_pub_key_pem = "PEER-PUBLIC-KEY"
        agent._signing_key_obj = object()
        agent._serial_num = "email-send-serial"
        agent.packet_ttl = 3600
        agent.email_message_send_packet_identifier = hashlib.sha256(
            b"email-send-serialemail-send-message"
        ).hexdigest()
        agent.logs = []

        def log(message=None, **kwargs):
            agent.logs.append((message, kwargs))

        agent.log = log
        return agent

    def test_encrypted_alert_hides_subject_and_body_and_uses_assigned_keys(self):
        agent = self._agent(True)
        captured = {}

        def secure(payload, **kwargs):
            captured["payload"] = payload
            captured.update(kwargs)
            return {"content": "sealed", "sig": "signed", "serial": kwargs["serial_num"]}

        self.module.wrap_packet_securely = secure
        agent.cmd_send_alert_msg(
            {
                "cause": "SSH Login Detected",
                "formatted_msg": "root logged in from 192.0.2.10",
                "level": "warning",
            },
            {"origin": "ssh-watch"},
        )

        self.assertEqual(len(agent.queue.items), 1)
        queued = agent.queue.items[0]
        self.assertEqual(queued["subject"], "MatrixSwarm Encrypted Alert")
        marker, encoded = queued["body"].splitlines()
        self.assertEqual(marker, "MATRIXSWARM-ENCRYPTED-ALERT-V1")
        envelope = json.loads(base64.b64decode(encoded).decode("utf-8"))
        self.assertEqual(envelope["content"]["content"], "sealed")
        self.assertNotIn("SSH Login Detected", queued["body"])
        self.assertNotIn("192.0.2.10", queued["body"])

        self.assertEqual(captured["peer_pub_key_pem"], "PEER-PUBLIC-KEY")
        self.assertIs(captured["signing_key_obj"], agent._signing_key_obj)
        self.assertEqual(captured["serial_num"], "email-send-serial")
        self.assertEqual(
            captured["extra_fields"]["hash"],
            agent.email_message_send_packet_identifier,
        )
        self.assertGreater(captured["extra_fields"]["expires"], 0)
        self.assertEqual(captured["payload"]["content"]["subject"], "SSH Login Detected")
        self.assertEqual(captured["payload"]["content"]["origin"], "ssh-watch")

    def test_encryption_failure_never_downgrades_to_plaintext(self):
        agent = self._agent(True)

        def fail(*args, **kwargs):
            raise RuntimeError("secure wrapper unavailable")

        self.module.wrap_packet_securely = fail
        agent.cmd_send_alert_msg(
            {"cause": "Sensitive alert", "msg": "sensitive body"},
            {"origin": "watcher"},
        )

        self.assertEqual(agent.queue.items, [])
        self.assertTrue(any("SEND_BLOCKED" in (message or "") for message, _ in agent.logs))

    def test_missing_assigned_keys_blocks_encrypted_alert(self):
        agent = self._agent(True)
        agent._peer_pub_key_pem = None
        agent.cmd_send_alert_msg(
            {"cause": "Sensitive alert", "msg": "sensitive body"},
            {"origin": "watcher"},
        )
        self.assertEqual(agent.queue.items, [])

    def test_plaintext_alert_behavior_is_preserved_when_option_is_off(self):
        agent = self._agent(False)
        agent.cmd_send_alert_msg(
            {"cause": "Ordinary alert", "formatted_msg": "ordinary body"},
            {"origin": "watcher"},
        )

        self.assertEqual(len(agent.queue.items), 1)
        queued = agent.queue.items[0]
        self.assertEqual(queued["subject"], "Ordinary alert")
        self.assertEqual(queued["body"], "ordinary body")
        self.assertEqual(queued["encryption"], "STARTTLS")

    def test_editor_exposes_boolean_and_preserves_service_manager_metadata(self):
        source = EDITOR_PATH.read_text(encoding="utf-8")
        self.assertIn('QCheckBox("Encrypt alert email subject and body")', source)
        self.assertIn('cfg.get("encrypt_alerts", False)', source)
        self.assertIn('"encrypt_alerts": self.encrypt_alerts.isChecked()', source)
        self.assertIn('first = dict(service_manager[0])', source)
        self.assertIn('service_manager = [first, *service_manager[1:]]', source)

    def test_agent_metadata_defaults_to_compatible_plaintext_mode(self):
        metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
        self.assertIs(metadata["config"]["encrypt_alerts"], False)
        self.assertEqual(
            metadata["config"]["service-manager"][0]["scope"],
            ["parent", "any"],
        )

    def test_sources_compile(self):
        for path in (AGENT_PATH, EDITOR_PATH):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


if __name__ == "__main__":
    unittest.main()
