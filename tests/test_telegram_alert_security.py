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
TELEGRAM_AGENT = (
    ROOT / "matrixos/agents/python_core/telegram_relay/telegram_relay.py"
)
EMAIL_AGENT = ROOT / "matrixos/agents/python_core/email_send/email_send.py"
TELEGRAM_META = ROOT / "phoenix/agents_meta/telegram_relay.json"
EMAIL_META = ROOT / "phoenix/agents_meta/email_send.json"
TELEGRAM_EDITOR = (
    ROOT
    / "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/telegram_relay.py"
)
EMAIL_EDITOR = (
    ROOT
    / "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/email_send.py"
)
TELEGRAM_PANEL = (
    ROOT
    / "phoenix/matrix_gui/core/panel/custom_panels/telegram_relay/telegram_relay.py"
)


class _BootAgent:
    pass


class _Identity:
    pass


def _install_module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module


def _load_telegram_agent():
    os.environ.setdefault("SITE_ROOT", str(ROOT))
    os.environ.setdefault("AGENT_PATH", str(ROOT / "matrixos/agents/python_core"))

    _install_module("requests", post=lambda *args, **kwargs: None)
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
        "core.python_core.utils.crypto_utils",
        pem_fix=lambda value: value,
    )
    _install_module(
        "core.python_core.utils.swarm_sleep",
        interruptible_sleep=lambda *args, **kwargs: None,
    )
    _install_module("Crypto")
    _install_module(
        "Crypto.PublicKey",
        RSA=types.SimpleNamespace(import_key=lambda value: value),
    )

    module_name = "telegram_alert_security_under_test"
    spec = importlib.util.spec_from_file_location(module_name, TELEGRAM_AGENT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class TelegramAlertSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_telegram_agent()

    def _agent(self, *, enabled=True, encrypted=True):
        agent = self.module.Agent.__new__(self.module.Agent)
        agent.alerts_enabled = enabled
        agent.encrypt_alerts = encrypted
        agent._peer_pub_key_pem = "PEER-PUBLIC-KEY"
        agent._signing_key_obj = object()
        agent._serial_num = "telegram-relay-serial"
        agent.packet_ttl = 3600
        agent.telegram_message_send_packet_identifier = hashlib.sha256(
            b"telegram-relay-serialtelegram-relay-message"
        ).hexdigest()
        agent.sent = []
        agent.logs = []
        agent.send_to_telegram = lambda message: agent.sent.append(message) or True
        agent.log = lambda message=None, **kwargs: agent.logs.append((message, kwargs))
        return agent

    def test_encrypted_alert_hides_plaintext_and_uses_assigned_keys(self):
        agent = self._agent()
        captured = {}

        def secure(payload, **kwargs):
            captured["payload"] = payload
            captured.update(kwargs)
            return {"content": "sealed", "sig": "signed"}

        self.module.wrap_packet_securely = secure
        agent.cmd_send_alert_msg(
            {
                "formatted_msg": "root logged in from 192.0.2.10",
                "level": "warning",
            },
            {"origin": "gatekeeper"},
        )

        self.assertEqual(1, len(agent.sent))
        marker, encoded = agent.sent[0].splitlines()
        self.assertEqual("MATRIXSWARM-ENCRYPTED-ALERT-V1", marker)
        envelope = json.loads(base64.b64decode(encoded).decode("utf-8"))
        self.assertEqual("sealed", envelope["content"]["content"])
        self.assertNotIn("192.0.2.10", agent.sent[0])
        self.assertEqual("telegram_relay.alert", captured["payload"]["handler"])
        self.assertEqual("gatekeeper", captured["payload"]["content"]["origin"])
        self.assertEqual("PEER-PUBLIC-KEY", captured["peer_pub_key_pem"])
        self.assertIs(agent._signing_key_obj, captured["signing_key_obj"])
        self.assertEqual(
            agent.telegram_message_send_packet_identifier,
            captured["extra_fields"]["hash"],
        )

    def test_disabled_alert_is_not_sent(self):
        agent = self._agent(enabled=False, encrypted=False)
        agent.cmd_send_alert_msg({"msg": "must not send"}, {"origin": "watcher"})
        self.assertEqual([], agent.sent)

    def test_plaintext_mode_is_preserved_when_encryption_is_off(self):
        agent = self._agent(encrypted=False)
        agent.cmd_send_alert_msg({"formatted_msg": "ordinary alert"}, {})
        self.assertEqual(["ordinary alert"], agent.sent)

    def test_encryption_failure_never_downgrades_to_plaintext(self):
        agent = self._agent()

        def fail(*args, **kwargs):
            raise RuntimeError("secure wrapper unavailable")

        self.module.wrap_packet_securely = fail
        agent.cmd_send_alert_msg({"msg": "sensitive body"}, {"origin": "watcher"})
        self.assertEqual([], agent.sent)
        self.assertTrue(
            any("SEND_BLOCKED" in (message or "") for message, _ in agent.logs)
        )

    def test_metadata_and_editors_expose_alert_controls(self):
        telegram = json.loads(TELEGRAM_META.read_text(encoding="utf-8"))
        email = json.loads(EMAIL_META.read_text(encoding="utf-8"))

        self.assertIs(telegram["config"]["alerts_enabled"], True)
        self.assertIs(telegram["config"]["encrypt_alerts"], False)
        self.assertEqual(
            ["telegram_relay.telegram_relay"],
            telegram["config"]["ui"]["panel"],
        )
        self.assertTrue(
            any("packet_signing" in item for item in telegram["constraints"])
        )
        self.assertIs(email["config"]["alerts_enabled"], True)

        telegram_editor = TELEGRAM_EDITOR.read_text(encoding="utf-8")
        email_editor = EMAIL_EDITOR.read_text(encoding="utf-8")
        self.assertIn('cfg.get("alerts_enabled", True)', telegram_editor)
        self.assertIn('cfg.get("encrypt_alerts", False)', telegram_editor)
        self.assertIn('cfg.get("alerts_enabled", True)', email_editor)
        self.assertIn('"alerts_enabled": self.alerts_enabled.isChecked()', email_editor)

    def test_candidate_sources_compile(self):
        for path in (
            TELEGRAM_AGENT,
            EMAIL_AGENT,
            TELEGRAM_EDITOR,
            EMAIL_EDITOR,
            TELEGRAM_PANEL,
        ):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


if __name__ == "__main__":
    unittest.main()
