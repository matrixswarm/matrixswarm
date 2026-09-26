from pathlib import Path
import ast
import hashlib
import posixpath
import unittest
import uuid
from copy import deepcopy
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "matrixos/agents/python_core/matrix_ssh/matrix_ssh.py"
CONNECTOR = ROOT / "phoenix/matrix_gui/modules/net/connector/egress/ssh.py"
CONFIG_EDITOR = ROOT / "phoenix/matrix_gui/swarm_workspace/cls_lib/agent/config_editors/matrix_ssh.py"
DEPLOYMENT_CONNECTOR = ROOT / "phoenix/matrix_gui/modules/net/deployment_connector.py"
LAUNCHER = ROOT / "phoenix/matrix_gui/modules/net/class_lib/processes/connection_launcher.py"
DIRECTIVE_COMPILER = ROOT / "phoenix/matrix_gui/swarm_workspace/cls_lib/deployment/directive_compiler.py"
DEPLOYMENT_COMPILER = ROOT / "phoenix/matrix_gui/swarm_workspace/cls_lib/deployment/deployment_compiler.py"
META = ROOT / "phoenix/agents_meta/matrix_ssh.json"


def load_functions(path, names, namespace=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    target = dict(namespace or {})
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), target)
    return target


def load_class(path, name, namespace=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    class_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )
    target = dict(namespace or {})
    exec(compile(ast.Module(body=[class_node], type_ignores=[]), str(path), "exec"), target)
    return target[name]


class MatrixSSHTransportTests(unittest.TestCase):
    def test_lockdown_config_uses_typed_boolean_semantics(self):
        parse = load_functions(AGENT, {"_parse_bool"})["_parse_bool"]
        for value in (False, 0, "false", "False", "0", "off", ""):
            with self.subTest(value=value):
                self.assertFalse(parse(value))
        for value in (True, 1, "true", "True", "1", "on"):
            with self.subTest(value=value):
                self.assertTrue(parse(value))
        with self.assertRaises(ValueError):
            parse("maybe")

        editor = CONFIG_EDITOR.read_text(encoding="utf-8")
        self.assertIn("class MatrixSsh", editor)
        self.assertIn("QCheckBox", editor)
        self.assertIn('"lockdown_state": self.lockdown_checkbox.isChecked()', editor)

    def test_durable_inbox_matches_agent_and_phoenix(self):
        agent = load_functions(
            AGENT,
            {"persistent_inbox"},
            {"Path": Path, "_SAFE_COMPONENT": __import__("re").compile(
                r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
            )},
        )
        connector = load_functions(
            CONNECTOR,
            {"remote_inbox"},
            {"posixpath": __import__("posixpath"), "_SAFE_COMPONENT": __import__("re").compile(
                r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
            )},
        )
        local = agent["persistent_inbox"]("/matrix", "phoenix", "matrix-ssh-a1")
        remote = connector["remote_inbox"]("phoenix", "matrix-ssh-a1")
        self.assertTrue(
            local.as_posix().endswith(remote),
            f"{local.as_posix()} does not end with {remote}",
        )
        self.assertEqual(
            "/matrix/universes/static/phoenix/persistent/matrix-ssh-a1/comm/incoming",
            remote,
        )

    def test_path_components_fail_closed(self):
        connector = load_functions(
            CONNECTOR,
            {"remote_inbox"},
            {"posixpath": __import__("posixpath"), "_SAFE_COMPONENT": __import__("re").compile(
                r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
            )},
        )
        for universe, uid in (("../root", "matrix-ssh"), ("good", "bad/name")):
            with self.subTest(universe=universe, uid=uid):
                with self.assertRaises(ValueError):
                    connector["remote_inbox"](universe, uid)

    def test_agent_and_connector_use_same_signed_recipient_tag(self):
        expected = hashlib.sha256(b"serial-1matrix-ssh-ingress").hexdigest()
        for path in (AGENT, CONNECTOR):
            with self.subTest(path=path.name):
                loaded = load_functions(path, {"recipient_hash"}, {"hashlib": hashlib})
                self.assertEqual(expected, loaded["recipient_hash"]("serial-1"))

    def test_transport_is_double_wrapped_and_uploaded_atomically(self):
        text = CONNECTOR.read_text(encoding="utf-8")
        self.assertIn('"matrix_packet": packet_data', text)
        self.assertIn("wrap_packet_securely(", text)
        self.assertIn('extra_fields={"hash": self._recipient}', text)
        self.assertIn('self._sftp.file(temp_path, "wb")', text)
        self.assertIn("self._sftp.chown(temp_path, *inbox_owner)", text)
        self.assertIn("self._sftp.chmod(temp_path, 0o600)", text)
        self.assertIn("self._sftp.rename(temp_path, final_path)", text)
        self.assertLess(
            text.index("self._sftp.chown(temp_path, *inbox_owner)"),
            text.index("self._sftp.rename(temp_path, final_path)"),
        )
        self.assertNotIn("exec_command", text)

    def test_root_upload_is_reowned_before_atomic_publish(self):
        connector_class = load_class(
            CONNECTOR,
            "SSHConnector",
            {
                "BaseConnector": object,
                "posixpath": posixpath,
                "uuid": uuid,
            },
        )

        class Attrs:
            def __init__(self, uid, gid):
                self.st_uid = uid
                self.st_gid = gid

        class Writable:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def write(self, payload):
                self.payload = payload

            def flush(self):
                pass

        class FakeSFTP:
            def __init__(self, inbox):
                self.inbox = inbox
                self.temp_path = None
                self.events = []

            def stat(self, path):
                if path == self.inbox:
                    return Attrs(1001, 1001)
                if path == self.temp_path:
                    return Attrs(0, 0)
                raise OSError("not found")

            def file(self, path, mode):
                self.temp_path = path
                return Writable()

            def chown(self, path, uid, gid):
                self.events.append(("chown", path, uid, gid))

            def chmod(self, path, mode):
                self.events.append(("chmod", path, mode))

            def rename(self, source, target):
                self.events.append(("rename", source, target))

            def remove(self, path):
                self.events.append(("remove", path))

        connector = object.__new__(connector_class)
        connector.inbox = "/matrix/incoming"
        connector._sftp = FakeSFTP(connector.inbox)
        connector._ensure_connected = lambda: None
        connector._upload("a" * 32, b"{}")

        self.assertEqual("chown", connector._sftp.events[0][0])
        self.assertEqual((1001, 1001), connector._sftp.events[0][2:])
        self.assertEqual("chmod", connector._sftp.events[1][0])
        self.assertEqual(0o600, connector._sftp.events[1][2])
        self.assertEqual("rename", connector._sftp.events[2][0])
        self.assertTrue(connector._sftp.events[2][2].endswith(".packet"))

    def test_agent_claims_then_relays_to_dynamic_matrix_id(self):
        text = AGENT.read_text(encoding="utf-8")
        self.assertIn("os.replace(packet_path, claimed)", text)
        self.assertIn("unwrap_secure_packet(", text)
        self.assertIn('"handler": "cmd_the_source"', text)
        self.assertIn("self.get_matrix_universal_id()", text)
        self.assertNotIn('pass_packet(packet, "matrix")', text)

    def test_ssh_policy_supports_both_lifecycles(self):
        loaded = load_functions(DEPLOYMENT_CONNECTOR, {"_transport_policy"})
        policy = loaded["_transport_policy"]
        self.assertEqual((False, True), policy("ssh", {"ssh_mode": "one_shot"}))
        self.assertEqual((True, False), policy("ssh", {"ssh_mode": "persistent"}))
        with self.assertRaises(ValueError):
            policy("ssh", {"ssh_mode": "forever"})

    def test_delivery_mode_is_agent_owned_not_registry_owned(self):
        registry_editor = (
            ROOT / "phoenix/matrix_gui/registry/object_classes/editors/ssh.py"
        ).read_text(encoding="utf-8")
        registry_provider = (
            ROOT / "phoenix/matrix_gui/registry/object_classes/providers/ssh.py"
        ).read_text(encoding="utf-8")
        legacy_editor = (
            ROOT
            / "phoenix/matrix_gui/modules/net/connection_types/editors/ssh_editor.py"
        ).read_text(encoding="utf-8")

        for source in (registry_editor, registry_provider, legacy_editor):
            self.assertNotIn("Matrix SSH Delivery", source)
            self.assertNotIn('data.get("ssh_mode"', source)
        self.assertNotIn('"ssh_mode": self.ssh_mode', registry_editor)

        matrix_editor = CONFIG_EDITOR.read_text(encoding="utf-8")
        self.assertIn("SSH Delivery Mode:", matrix_editor)
        self.assertIn('cfg.get("ssh_mode", "one_shot")', matrix_editor)
        self.assertIn('"ssh_mode": self.ssh_mode.currentData()', matrix_editor)

        import json

        meta = json.loads(META.read_text(encoding="utf-8"))
        self.assertEqual("one_shot", meta["config"]["ssh_mode"])

    def test_active_persistent_launcher_submits_instead_of_restarting(self):
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('submit = getattr(existing_instance, "submit", None)', text)
        self.assertIn("not submit(packet)", text)

    def test_ssh_credentials_are_deployment_only(self):
        import json

        meta = json.loads(META.read_text(encoding="utf-8"))
        ssh = next(item["matrix_ssh"] for item in meta["constraints"] if "matrix_ssh" in item)
        self.assertEqual(1, ssh["inject_in_connection"])
        self.assertEqual(1, ssh["deployment_only"])
        self.assertEqual("outgoing.command", meta["connection"]["channel"])

        tree = ast.parse(DIRECTIVE_COMPILER.read_text(encoding="utf-8"))
        compiler_class = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        namespace = {"deepcopy": deepcopy}
        exec(
            compile(ast.Module(body=[compiler_class], type_ignores=[]), "directive_compiler", "exec"),
            namespace,
        )
        secret_constraint = SimpleNamespace(
            is_deployment_only=lambda: True,
            handler=SimpleNamespace(
                directive_fields=lambda: {"private_key": "must-not-leak"},
                get_directory_path=lambda: ["config", "ssh"],
            ),
            fields={"private_key": "must-not-leak"},
        )
        ir = {
            "root": SimpleNamespace(
                universal_id="matrix-ssh",
                name="matrix_ssh",
                node={"serial": "serial", "config": {}},
                resolved={"ssh": secret_constraint},
                children=[],
            )
        }
        result = namespace["DirectiveCompiler"](ir, "root").compile()
        self.assertNotIn("ssh", result["agents"]["config"])
        self.assertNotIn("must-not-leak", str(result))

        private_tree = ast.parse(DEPLOYMENT_COMPILER.read_text(encoding="utf-8"))
        deployment_class = next(
            node for node in private_tree.body if isinstance(node, ast.ClassDef)
        )

        class FakeConstraint:
            pass

        class DeploymentOnlySSH(FakeConstraint):
            path = ["ssh"]

            def get_editor(self):
                return SimpleNamespace(is_connection=lambda: False)

            def inject_into_connection(self):
                return True

            def is_deployment_only(self):
                return True

            def get_fields(self):
                return {
                    "proto": "ssh",
                    "channel": "ssh",
                    "private_key": "vault-only",
                }

        private_ir = {
            "root": SimpleNamespace(
                universal_id="matrix-ssh",
                name="matrix_ssh",
                node={
                    "serial": "serial",
                    "config": {"ssh_mode": "persistent"},
                    "meta": {
                        "connection": {"channel": "outgoing.command"},
                    },
                },
                resolved={"ssh": DeploymentOnlySSH()},
                children=[],
            )
        }
        private_namespace = {
            "Constraint": FakeConstraint,
            "AutoGenConstraint": SimpleNamespace(set_nested=lambda *args: None),
        }
        exec(
            compile(ast.Module(body=[deployment_class], type_ignores=[]), "deployment_compiler", "exec"),
            private_namespace,
        )
        private = private_namespace["DeploymentCompiler"](private_ir, "root").compile()
        self.assertEqual("vault-only", private["agents"]["connection"]["private_key"])
        self.assertEqual(
            "outgoing.command",
            private["agents"]["connection"]["channel"],
        )
        self.assertEqual(
            "persistent",
            private["agents"]["connection"]["ssh_mode"],
        )
        self.assertEqual({}, private["certs"])


if __name__ == "__main__":
    unittest.main()
