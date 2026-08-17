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
DISCORD_AGENT = ROOT / "matrixos/agents/python_core/discord_relay/discord_relay.py"
DISCORD_META = ROOT / "phoenix/agents_meta/discord_relay.json"
DISCORD_EDITOR = (
    ROOT
    / "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/discord_relay.py"
)
DISCORD_PANEL = (
    ROOT
    / "phoenix/matrix_gui/core/panel/custom_panels/discord_relay/discord_relay.py"
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
    return module


def _load_discord_agent():
    os.environ.setdefault("SITE_ROOT", str(ROOT))
    os.environ.setdefault("AGENT_PATH", str(ROOT / "matrixos/agents/python_core"))

    discord = _install_module(
        "discord",
        Intents=types.SimpleNamespace(default=lambda: types.SimpleNamespace()),
        Color=types.SimpleNamespace(),
        Embed=object,
        File=object,
    )
    discord.__path__ = []
    discord_ext = _install_module("discord.ext")
    discord_ext.__path__ = []
    commands = _install_module("discord.ext.commands", Bot=object)
    discord.ext = discord_ext
    discord_ext.commands = commands

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

    module_name = "discord_alert_security_under_test"
    spec = importlib.util.spec_from_file_location(module_name, DISCORD_AGENT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class DiscordAlertSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_discord_agent()

    def _agent(self, *, enabled=True, encrypted=True):
        agent = self.module.Agent.__new__(self.module.Agent)
        agent.alerts_enabled = enabled
        agent.encrypt_alerts = encrypted
        agent._peer_pub_key_pem = "PEER-PUBLIC-KEY"
        agent._signing_key_obj = object()
        agent._serial_num = "discord-relay-serial"
        agent.packet_ttl = 3600
        agent.discord_message_send_packet_identifier = hashlib.sha256(
            b"discord-relay-serialdiscord-relay-message"
        ).hexdigest()
        agent.sent = []
        agent.embeds = []
        agent.logs = []
        agent.send_encrypted_alert_to_discord = (
            lambda message: agent.sent.append(message) or True
        )
        agent.send_to_discord = lambda message: agent.sent.append(message) or True
        agent.send_embed_from_data = lambda embed: agent.embeds.append(embed) or True
        agent.log = lambda message=None, **kwargs: agent.logs.append((message, kwargs))
        return agent

    def test_encrypted_alert_hides_server_details_and_uses_assigned_keys(self):
        agent = self._agent()
        captured = {}

        def secure(payload, **kwargs):
            captured["payload"] = payload
            captured.update(kwargs)
            return {"content": "sealed", "sig": "signed"}

        self.module.wrap_packet_securely = secure
        agent.cmd_send_alert_msg(
            {
                "embed_data": {
                    "title": "Apache crashed",
                    "description": "Host web-01 failed at /srv/private/site",
                    "footer": "Restart required",
                },
                "level": "critical",
            },
            {"origin": "apache-watchdog"},
        )

        self.assertEqual(1, len(agent.sent))
        marker, encoded = agent.sent[0].splitlines()
        self.assertEqual("MATRIXSWARM-ENCRYPTED-ALERT-V1", marker)
        envelope = json.loads(base64.b64decode(encoded).decode("utf-8"))
        self.assertEqual("sealed", envelope["content"]["content"])
        self.assertNotIn("web-01", agent.sent[0])
        self.assertNotIn("/srv/private/site", agent.sent[0])
        self.assertEqual("discord_relay.alert", captured["payload"]["handler"])
        self.assertIn("Apache crashed", captured["payload"]["content"]["message"])
        self.assertEqual(
            "apache-watchdog", captured["payload"]["content"]["origin"]
        )
        self.assertEqual("PEER-PUBLIC-KEY", captured["peer_pub_key_pem"])
        self.assertIs(agent._signing_key_obj, captured["signing_key_obj"])
        self.assertEqual(
            agent.discord_message_send_packet_identifier,
            captured["extra_fields"]["hash"],
        )
        self.assertEqual([], agent.embeds)

    def test_disabled_alert_is_not_sent(self):
        agent = self._agent(enabled=False, encrypted=False)
        agent.cmd_send_alert_msg({"msg": "must not send"}, {"origin": "watcher"})
        self.assertEqual([], agent.sent)
        self.assertEqual([], agent.embeds)

    def test_legacy_instance_without_alert_flag_defaults_to_enabled(self):
        agent = self._agent(encrypted=False)
        del agent.alerts_enabled
        agent.cmd_send_alert_msg({"formatted_msg": "legacy alert"}, {})
        self.assertEqual(["legacy alert"], agent.sent)

    def test_plaintext_mode_preserves_native_rich_embed(self):
        agent = self._agent(encrypted=False)
        embed = {"title": "Ordinary alert", "description": "details"}
        agent.cmd_send_alert_msg({"embed_data": embed}, {})
        self.assertEqual([embed], agent.embeds)
        self.assertEqual([], agent.sent)

    def test_encryption_failure_never_downgrades_to_plaintext(self):
        agent = self._agent()

        def fail(*args, **kwargs):
            raise RuntimeError("secure wrapper unavailable")

        self.module.wrap_packet_securely = fail
        agent.cmd_send_alert_msg(
            {"msg": "sensitive server body"}, {"origin": "watcher"}
        )
        self.assertEqual([], agent.sent)
        self.assertTrue(
            any("SEND_BLOCKED" in (message or "") for message, _ in agent.logs)
        )

    def test_oversized_encrypted_alert_uses_attachment_without_plaintext(self):
        agent = self._agent()
        agent.send_encrypted_alert_to_discord = types.MethodType(
            self.module.Agent.send_encrypted_alert_to_discord,
            agent,
        )
        captured = {}

        class FakeFile:
            def __init__(self, fp, filename):
                self.fp = fp
                self.filename = filename

        class PendingSend:
            def close(self):
                pass

        class Channel:
            def send(self, content, file=None):
                captured["content"] = content
                captured["file"] = file
                return PendingSend()

        channel = Channel()
        agent.bot = types.SimpleNamespace(
            get_channel=lambda channel_id: channel,
            loop=object(),
        )
        agent.channel_id = 123

        original_file = self.module.discord_real.File
        original_schedule = self.module.asyncio.run_coroutine_threadsafe
        self.module.discord_real.File = FakeFile

        def schedule(coroutine, loop):
            captured["scheduled"] = True
            coroutine.close()
            return object()

        self.module.asyncio.run_coroutine_threadsafe = schedule
        try:
            encrypted = "MATRIXSWARM-ENCRYPTED-ALERT-V1\n" + ("A" * 2000)
            self.assertTrue(agent.send_encrypted_alert_to_discord(encrypted))
        finally:
            self.module.discord_real.File = original_file
            self.module.asyncio.run_coroutine_threadsafe = original_schedule

        self.assertTrue(captured["scheduled"])
        self.assertEqual(encrypted.encode("utf-8"), captured["file"].fp.getvalue())
        self.assertNotIn("A" * 100, captured["content"])
        self.assertTrue(captured["file"].filename.endswith(".txt"))

    def test_metadata_editor_and_panel_expose_security_contract(self):
        discord = json.loads(DISCORD_META.read_text(encoding="utf-8"))
        self.assertIs(discord["config"]["alerts_enabled"], True)
        self.assertIs(discord["config"]["encrypt_alerts"], False)
        self.assertEqual(3600, discord["config"]["packet_ttl"])
        self.assertEqual(
            ["discord_relay.discord_relay"],
            discord["config"]["ui"]["panel"],
        )
        self.assertTrue(
            any("packet_signing" in item for item in discord["constraints"])
        )
        self.assertIs(
            discord["config"]["service-manager"][0]["auth"]["sig"], True
        )

        editor = DISCORD_EDITOR.read_text(encoding="utf-8")
        panel = DISCORD_PANEL.read_text(encoding="utf-8")
        self.assertIn('cfg.get("alerts_enabled", True)', editor)
        self.assertIn('cfg.get("encrypt_alerts", False)', editor)
        self.assertIn('"alerts_enabled": self.alerts_enabled.isChecked()', editor)
        self.assertIn("class DiscordRelay(PhoenixPanelInterface)", panel)
        self.assertIn('fetch_fresh(target="deployment")', panel)

    def test_candidate_sources_compile(self):
        for path in (DISCORD_AGENT, DISCORD_EDITOR, DISCORD_PANEL):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


if __name__ == "__main__":
    unittest.main()