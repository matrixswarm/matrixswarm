import ast
import importlib.util
from pathlib import Path
import shlex
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
            directive_path="/matrix/boot_directives/phoenix.enc.json",
            swarm_key="c2VhbGVkLXN3YXJtLWtleQ==",
            boot_flags=("--debug",),
        )
        self.assertNotIn("{universe}", command)
        self.assertNotIn("{directive", command)
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

    def test_linux_accounts_fail_closed(self):
        helper = load_module(self.shell_helper_path, "remote_linux_users")
        self.assertEqual(helper.default_linux_user("phoenix"), "matrix-phoenix")
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

        command = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
            directive_path="/matrix/boot_directives/phoenix.enc.json",
            swarm_key="c2VhbGVkLXN3YXJtLWtleQ==",
            runtime_capabilities=capabilities,
        )
        self.assertIn("/usr/bin/systemctl restart httpd.service", command)
        self.assertIn("matrix-secure-readers", command)
        self.assertIn("setfacl", command)

        with self.assertRaises(ValueError):
            helper.validate_runtime_capabilities(
                {"watchdog_services": ["sshd.service"]}
            )

    def test_remote_command_redacts_swarm_key(self):
        helper = load_module(self.shell_helper_path, "remote_secret_redaction")
        secret = "c2VhbGVkLXN3YXJtLWtleQ=="
        command = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
            directive_path="/matrix/boot_directives/phoenix.enc.json",
            swarm_key=secret,
        )
        self.assertNotIn(secret, helper.redact_remote_secret(command, secret))

    def test_spawn_audit_is_inside_the_universe_static_tree(self):
        spawner = source("matrixos/core/python_core/core_spawner.py")
        self.assertNotIn('open("/matrix/spawn.log"', spawner)
        self.assertIn('Path(self.pm.session.static_root) / "spawn.log"', spawner)


if __name__ == "__main__":
    unittest.main()
