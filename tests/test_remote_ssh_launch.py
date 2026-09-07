import ast
import base64
import importlib.util
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def load_module(relative_path, module_name):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RemoteSSHLaunchTests(unittest.TestCase):
    shell_helper_path = "phoenix/matrix_gui/modules/railgun/remote_shell.py"
    launcher_paths = (
        "phoenix/matrix_gui/modules/directive/deploy_dialog.py",
        "phoenix/matrix_gui/swarm_workspace/cls_lib/deployment/dialog/railgun.py",
    )

    def test_background_launchers_do_not_allocate_a_pty(self):
        for path in self.launcher_paths:
            with self.subTest(path=path):
                text = source(path)
                tree = ast.parse(text, filename=path)
                calls = (
                    node.func.attr
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                )
                self.assertNotIn("get_pty", calls)

    def test_background_launchers_do_not_attach_verbose_agents(self):
        deploy_source = source(self.launcher_paths[0])
        self.assertIn("self.flag_verbose.setEnabled(False)", deploy_source)
        self.assertNotIn('flags.append("--verbose")', deploy_source)

        railgun_source = source(self.launcher_paths[1])
        self.assertIn("--verbose suppressed for detached SSH boot", railgun_source)
        self.assertIn(
            'for flag in ["debug", "clean", "reboot", "rug_pull", "reboot_new"]',
            railgun_source,
        )

    def test_launchers_use_installed_venv_and_drain_channels(self):
        helper_source = source(self.shell_helper_path)
        self.assertIn("/matrix/.venv/bin/python3", helper_source)
        self.assertIn("PYTHONUNBUFFERED=1", helper_source)
        self.assertIn("runuser -u", helper_source)
        for path in self.launcher_paths:
            with self.subTest(path=path):
                text = source(path)
                self.assertNotIn("source /matrix/venv", text)
                self.assertIn("while chan.recv_ready()", text)
                self.assertIn("while chan.recv_stderr_ready()", text)
                self.assertIn("client.close()", text)
                self.assertIn("build_remote_matrixd_command", text)

    def test_remote_shell_tokens_fail_closed(self):
        helper = load_module(self.shell_helper_path, "remote_shell_policy")
        self.assertEqual(
            "phoenix-2026_08.14",
            helper.validate_remote_token("phoenix-2026_08.14", "Universe"),
        )

        for payload in (
            "",
            "phoenix; id",
            "phoenix$(id)",
            "phoenix`id`",
            "phoenix\nwhoami",
            "../phoenix",
            "p" * 129,
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    helper.validate_remote_token(payload, "Universe")

    def test_remote_shell_data_is_one_quoted_argument(self):
        helper = load_module(self.shell_helper_path, "remote_shell_quoting")
        payload = "/matrix/boot directives/phoenix; touch PWNED.enc.json"
        quoted = helper.quote_remote_argument(payload, "Directive path")
        self.assertEqual([payload], shlex.split(quoted))

        for rejected in ("", "line\nbreak", "carriage\rreturn", "nul\x00byte"):
            with self.subTest(rejected=rejected):
                with self.assertRaises(ValueError):
                    helper.quote_remote_argument(rejected, "Directive path")

    def test_launchers_never_interpolate_untrusted_shell_values(self):
        helper = load_module(self.shell_helper_path, "remote_shell_builder")
        command = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
            boot_flags=("--debug",),
            runtime_capabilities={"mcp_worker": True},
        )
        self.assertNotIn("{universe}", command)
        self.assertNotIn("{directive", command)
        self.assertIn("--directive-stdin", command)
        self.assertNotIn("/matrix/boot_directives", command)
        self.assertNotIn("SWARM_KEY=", command)
        self.assertIn("matrix-phoenix-mcp", command)
        for path in self.launcher_paths:
            with self.subTest(path=path):
                text = source(path)
                self.assertIn("validate_remote_token", text)
                self.assertIn(
                    "universe = validate_remote_token(",
                    text,
                )
                self.assertNotIn("--universe {universe}", text)
                self.assertNotIn("--directive {directive_remote}", text)
                self.assertNotIn("--directive {remote_bundle}", text)
                self.assertNotIn("--reboot-id {self.opts", text)

    def test_linux_accounts_fail_closed_and_are_separate(self):
        helper = load_module(self.shell_helper_path, "remote_linux_users")
        self.assertEqual(helper.default_linux_user("phoenix"), "matrix-phoenix")
        self.assertEqual(
            helper.mcp_worker_linux_user("matrix-phoenix"),
            "matrix-phoenix-mcp",
        )
        for unsafe in (
            "root", "ubuntu", "Matrix", "matrix phoenix", "../matrix", "m" * 32
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    helper.validate_linux_user(unsafe)

    def test_directive_capabilities_are_narrow_and_validated(self):
        helper = load_module(self.shell_helper_path, "remote_capabilities")
        tree = {
            "name": "matrix",
            "children": [
                {"name": "apache_watchdog", "config": {"service_name": "httpd"}},
                {"name": "redis_watchdog", "config": {"service_name": "redis"}},
                {"name": "mysql_watchdog", "config": {"service_name": "mysqld"}},
                {"name": "gatekeeper"},
                {"name": "mcp_reflex"},
                {
                    "name": "wordpress_plugin_guard",
                    "config": {
                        "plugin_dir": "/var/www/html/wordpress/wp-content/plugins",
                        "quarantine_dir": "/opt/quarantine/wp_plugins",
                        "trusted_plugins_path": "/opt/swarm/guard/trusted_plugins.json",
                    },
                },
            ],
        }
        capabilities = helper.derive_runtime_capabilities(tree)
        self.assertEqual(
            capabilities["watchdog_services"],
            ["httpd.service", "redis.service", "mysqld.service"],
        )
        self.assertTrue(capabilities["gatekeeper_secure_log"])
        self.assertIsNotNone(capabilities["wordpress"])
        self.assertTrue(capabilities["mcp_worker"])

        command = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
            runtime_capabilities=capabilities,
        )
        self.assertIn("/usr/bin/systemctl restart httpd.service", command)
        self.assertIn("matrix-secure-readers", command)
        self.assertIn("setfacl", command)
        self.assertIn("matrix-phoenix-mcp", command)
        self.assertIn(
            "Plugin directory not found: %s",
            command,
        )
        root_shell = helper._root_shell
        helper._root_shell = lambda script: script
        try:
            raw_command = helper.build_remote_matrixd_command(
                action="start",
                universe="phoenix",
                linux_user="matrix-phoenix",
                runtime_capabilities=capabilities,
            )
        finally:
            helper._root_shell = root_shell

        self.assertIn(
            "printf '{\"worker_user\":\"%s\",\"working_directory\":\"%s\","
            "\"python\":\"/matrix/mcp/.venv/bin/python3\","
            "\"worker_script\":\"%s\",\"worker_sha256\":\"%s\"}\\n'",
            raw_command,
        )
        self.assertNotIn(
            "\"working_directory\":\"%s\",' '",
            raw_command,
        )
        profile_line = next(
            line
            for line in raw_command.splitlines()
            if line.startswith("printf '{\"worker_user\"")
        )
        shell_program = shutil.which("sh")
        if not shell_program:
            self.skipTest("POSIX sh is not available for profile rendering test")
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / "matrix-phoenix.json"
            shell = "\n".join(
                (
                    "MCP_USER=matrix-phoenix-mcp",
                    "MCP_WORK_DIR=/matrix/mcp/workers/phoenix",
                    "WORKER_SCRIPT=/matrix/agents/python_core/mcp_reflex/worker/mcp_stdio_worker.py",
                    f"WORKER_HASH={'a' * 64}",
                    f"PROFILE_TMP={shlex.quote(str(profile_path))}",
                    profile_line,
                )
            )
            subprocess.run(
                [shell_program, "-c", shell],
                check=True,
                capture_output=True,
                text=True,
            )
            profile = json.loads(profile_path.read_text(encoding="utf-8"))

        self.assertEqual(profile["worker_user"], "matrix-phoenix-mcp")
        self.assertEqual(
            profile["working_directory"], "/matrix/mcp/workers/phoenix"
        )
        self.assertEqual(profile["worker_sha256"], "a" * 64)

        with self.assertRaises(ValueError):
            helper.validate_runtime_capabilities(
                {"watchdog_services": ["sshd.service"]}
            )

        without_mcp = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
            runtime_capabilities={},
        )
        self.assertIn(
            'rm -f "/etc/sudoers.d/matrixswarm-$SWARM_USER-mcp"',
            without_mcp,
        )
        self.assertIn(
            'rm -f "/etc/matrixswarm/mcp-launchers/$SWARM_USER.json"',
            without_mcp,
        )
    def test_remote_command_never_contains_boot_secrets(self):
        helper = load_module(self.shell_helper_path, "remote_secret_boundary")
        secret = base64.b64encode(b"k" * 32).decode("ascii")
        bundle = {
            "nonce": base64.b64encode(b"n" * 12).decode("ascii"),
            "tag": base64.b64encode(b"t" * 16).decode("ascii"),
            "ciphertext": base64.b64encode(b"sealed-directive").decode("ascii"),
        }
        command = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
        )
        self.assertNotIn(secret, command)
        self.assertNotIn(bundle["ciphertext"], command)
        self.assertNotIn("SWARM_KEY", command)
        self.assertIn("--directive-stdin", command)

        class Channel:
            def __init__(self):
                self.payload = b""
                self.write_closed = False

            def sendall(self, payload):
                self.payload += payload

            def shutdown_write(self):
                self.write_closed = True

        channel = Channel()
        size = helper.send_boot_envelope(channel, bundle, secret)
        self.assertEqual(size, len(channel.payload))
        self.assertTrue(channel.write_closed)
        envelope = json.loads(channel.payload.decode("utf-8"))
        self.assertEqual(envelope["version"], 1)
        self.assertEqual(envelope["encrypted_bundle"], bundle)
        self.assertEqual(envelope["swarm_key"], secret)

    def test_remote_matrixd_is_probed_before_secret_transfer(self):
        helper = load_module(self.shell_helper_path, "remote_matrixd_probe")

        class Channel:
            def __init__(self, status):
                self.status = status

            def recv_exit_status(self):
                return self.status

        class Stream(io.BytesIO):
            def __init__(self, payload, status):
                super().__init__(payload)
                self.channel = Channel(status)

        class Client:
            def __init__(self, status):
                self.status = status
                self.command = None

            def exec_command(self, command, timeout):
                self.command = command
                return (
                    Stream(b"", self.status),
                    Stream(b"", self.status),
                    Stream(b"", self.status),
                )

        current = Client(0)
        self.assertTrue(helper.verify_remote_matrixd_stdin(current))
        self.assertIn("--directive-stdin", current.command)
        self.assertNotIn("swarm_key", current.command.lower())

        legacy = Client(65)
        with self.assertRaisesRegex(RuntimeError, "MatrixOS update required"):
            helper.verify_remote_matrixd_stdin(legacy)

        for path in self.launcher_paths:
            with self.subTest(path=path):
                launcher_source = source(path)
                probe_index = launcher_source.index(
                    "verify_remote_matrixd_stdin(client)"
                )
                send_index = launcher_source.index(
                    "payload_size = send_boot_envelope("
                )
                self.assertLess(probe_index, send_index)

    def test_matrixd_accepts_only_bounded_stdin_envelopes(self):
        matrixd_source = source("matrixos/scripts/matrixd")
        tree = ast.parse(matrixd_source, filename="matrixos/scripts/matrixd")
        selected = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.Assign))
            and (
                not isinstance(node, ast.FunctionDef)
                or node.name in {
                    "resolve_inline_swarm_key",
                    "read_boot_envelope",
                }
            )
        ]
        namespace = {
            "base64": base64,
            "json": json,
            "sys": __import__("sys"),
        }
        exec(compile(ast.Module(body=selected, type_ignores=[]), "matrixd", "exec"), namespace)

        key = base64.b64encode(b"k" * 32).decode("ascii")
        bundle = {
            "nonce": base64.b64encode(b"n" * 12).decode("ascii"),
            "tag": base64.b64encode(b"t" * 16).decode("ascii"),
            "ciphertext": base64.b64encode(b"ciphertext").decode("ascii"),
        }
        raw = json.dumps({
            "version": 1,
            "encrypted_bundle": bundle,
            "swarm_key": key,
        }).encode("utf-8")
        loaded_bundle, loaded_key = namespace["read_boot_envelope"](
            io.BytesIO(raw)
        )
        self.assertEqual(loaded_bundle, bundle)
        self.assertEqual(loaded_key, key)
        with self.assertRaises(ValueError):
            namespace["read_boot_envelope"](
                io.BytesIO(raw[:-1] + b',"extra":1}')
            )

        self.assertIn('boot.add_argument(\n        "--directive-stdin"', matrixd_source)
        self.assertIn("required=True", matrixd_source)
        self.assertNotIn('boot.add_argument("--directive"', matrixd_source)
        self.assertNotIn('boot.add_argument("--swarm_key"', matrixd_source)
        self.assertNotIn("def resolve_swarm_key", matrixd_source)
        self.assertIn("decrypt_directive_bundle(bundle, swarm_key)", matrixd_source)

    def test_new_deployments_never_write_generated_boot_files(self):
        deploy_source = source(
            "phoenix/matrix_gui/swarm_workspace/cls_lib/deployment/deploy.py"
        )
        railgun_source = source(
            "phoenix/matrix_gui/swarm_workspace/cls_lib/deployment/dialog/railgun.py"
        )
        self.assertNotIn("write_encrypted_bundle_to_file", deploy_source)
        self.assertNotIn("encrypted_path", deploy_source)
        self.assertNotIn("open_sftp", railgun_source)
        self.assertNotIn("sftp.put", railgun_source)
        self.assertIn('"encrypted_bundle": bundle', deploy_source)

    def test_spawn_audit_is_inside_the_universe_static_tree(self):
        spawner = source("matrixos/core/python_core/core_spawner.py")
        self.assertNotIn('open("/matrix/spawn.log"', spawner)
        self.assertIn('Path(self.pm.session.static_root) / "spawn.log"', spawner)


if __name__ == "__main__":
    unittest.main()
