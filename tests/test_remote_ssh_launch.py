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
        for path in self.launcher_paths:
            with self.subTest(path=path):
                text = source(path)
                self.assertIn("/matrix/.venv/bin/activate", text)
                self.assertNotIn("source /matrix/venv", text)
                self.assertIn("while chan.recv_ready()", text)
                self.assertIn("while chan.recv_stderr_ready()", text)
                self.assertIn("client.close()", text)

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
        for path in self.launcher_paths:
            with self.subTest(path=path):
                text = source(path)
                self.assertIn("quote_remote_argument", text)
                self.assertIn("validate_remote_token", text)
                self.assertIn(
                    "universe = validate_remote_token(",
                    text,
                )
                self.assertNotIn("--universe {universe}", text)
                self.assertNotIn("--directive {directive_remote}", text)
                self.assertNotIn("--directive {remote_bundle}", text)
                self.assertNotIn("--reboot-id {self.opts", text)


if __name__ == "__main__":
    unittest.main()
