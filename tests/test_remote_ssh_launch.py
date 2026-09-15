import ast
import base64
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def load_module(relative_path, module_name):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_matrixd(module_name):
    path = ROOT / "matrixos" / "scripts" / "matrixd"
    loader = importlib.machinery.SourceFileLoader(module_name, str(path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    original_path = list(sys.path)
    sys.path.insert(0, str(ROOT / "matrixos"))
    try:
        loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


class RemoteSSHLaunchTests(unittest.TestCase):
    shell_helper_path = "phoenix/matrix_gui/modules/railgun/remote_shell.py"
    launcher_paths = (
        "phoenix/matrix_gui/modules/directive/deploy_dialog.py",
        "phoenix/matrix_gui/swarm_workspace/cls_lib/deployment/dialog/railgun.py",
    )

    def test_ssh_selector_labels_disambiguate_duplicate_profiles(self):
        helper_source = source(
            "phoenix/matrix_gui/modules/railgun/ssh_support.py"
        )
        tree = ast.parse(helper_source, filename="ssh_support.py")
        selected = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "format_ssh_profile_label"
        ]
        namespace = {
            "clean_secret": lambda value: (
                str(value).strip() if value is not None else None
            )
        }
        exec(
            compile(
                ast.Module(body=selected, type_ignores=[]),
                "ssh_support.py",
                "exec",
            ),
            namespace,
        )
        profile = {
            "label": "production",
            "host": "203.0.113.10",
            "port": 2222,
            "username": "matrix",
            "trusted_host_fingerprint": "SHA256:abcdefghijklmnop",
        }
        label = namespace["format_ssh_profile_label"](
            "1234567890abcdef",
            profile,
        )
        self.assertIn("production", label)
        self.assertIn("matrix@203.0.113.10:2222", label)
        self.assertIn("id:90abcdef", label)
        self.assertIn("fp:…ghijklmnop", label)

        for path in (
            "phoenix/matrix_gui/modules/railgun/railgun_install_dialog.py",
            "phoenix/matrix_gui/modules/railgun/railgun_check_dialog.py",
            "phoenix/matrix_gui/modules/directive/deploy_options_dialog.py",
            "phoenix/matrix_gui/modules/directive/deploy_dialog.py",
        ):
            with self.subTest(path=path):
                self.assertIn("format_ssh_profile_label", source(path))

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
        self.assertIn('"protect_memory",', railgun_source)
        self.assertNotIn('self.opts.get("verbose"):\n                flags.append', railgun_source)

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

        control_source = source(self.launcher_paths[0])
        self.assertIn(
            "derive_runtime_capabilities(stored_agents)",
            control_source,
        )

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

    def test_universe_boundaries_are_root_owned_and_group_is_unique(self):
        helper = load_module(self.shell_helper_path, "universe_dac_boundary")
        root_shell = helper._root_shell
        helper._root_shell = lambda script: script
        try:
            command = helper.build_remote_matrixd_command(
                action="start",
                universe="phoenix",
                linux_user="matrix-phoenix",
                runtime_capabilities={"mcp_worker": True},
            )
        finally:
            helper._root_shell = root_shell

        self.assertIn("provision_isolated_account()", command)
        self.assertIn(
            'provision_isolated_account "$SWARM_USER"',
            command,
        )
        self.assertIn("SWARM_GROUP=$SWARM_USER", command)
        self.assertNotIn("SWARM_GROUP=$(provision_isolated_account", command)
        self.assertIn("CONFLICTING_PRIMARY", command)
        self.assertIn("CONFLICTING_MEMBER", command)
        self.assertIn(
            "chmod 0711 /matrix/universes /matrix/universes/runtime "
            "/matrix/universes/static",
            command,
        )
        self.assertIn(
            'chown root:"$SWARM_GROUP" "/matrix/universes/runtime/$UNIVERSE"',
            command,
        )
        self.assertIn(
            'chmod 0770 "/matrix/universes/runtime/$UNIVERSE"',
            command,
        )
        self.assertIn(
            'setfacl -R -P -b -- "/matrix/universes/runtime/$UNIVERSE"',
            command,
        )
        self.assertNotIn(
            'install -d -o "$SWARM_USER" -g "$SWARM_GROUP" -m 0700',
            command,
        )

        self.assertIn(
            'provision_isolated_account "$MCP_USER"',
            command,
        )
        self.assertIn("MCP_GROUP=$MCP_USER", command)
        self.assertNotIn("MCP_GROUP=$(provision_isolated_account", command)
        self.assertIn("chmod 0711 /matrix/mcp/workers", command)
        self.assertIn('chown root:"$MCP_GROUP" "$MCP_WORK_DIR"', command)
        self.assertIn('chmod 0770 "$MCP_WORK_DIR"', command)

        # Root refuses to execute MatrixOS if an account has made any shared
        # source file or directory writable or non-root-owned.
        audit_index = command.index("BAD_SOURCE=$(find /matrix")
        matrixd_index = command.index("matrixd boot --universe phoenix")
        self.assertLess(audit_index, matrixd_index)
        self.assertIn("! -user root -o -perm /022", command)
        self.assertIn("/matrix/mcp/.venv", command)

        mcp_launcher = source("matrixos/scripts/matrix-mcp-launch")
        self.assertIn("work_info.st_uid != 0", mcp_launcher)
        self.assertIn("work_info.st_gid != account.pw_gid", mcp_launcher)
        self.assertIn("work_mode & 0o007", mcp_launcher)
        self.assertIn(
            "working_directory is not a root-owned private worker boundary",
            mcp_launcher,
        )

    def test_directive_capabilities_are_narrow_and_validated(self):
        helper = load_module(self.shell_helper_path, "remote_capabilities")
        tree = {
            "name": "matrix",
            "children": [
                {"name": "apache_watchdog", "config": {"service_name": "httpd"}},
                {"name": "nginx_watchdog", "config": {"service_name": "nginx"}},
                {"name": "redis_watchdog", "config": {"service_name": "redis"}},
                {"name": "mysql_watchdog", "config": {"service_name": "mysqld"}},
                {"name": "gatekeeper"},
                {"name": "mcp_reflex"},
                {
                    "name": "wordpress_plugin_guard",
                    "config": {
                        "plugin_dir": "/var/www/html/wordpress/wp-content/plugins",
                        "quarantine_dir": "/opt/quarantine/wp_plugins",
                        "snapshot_root": "/opt/swarm/guard/snapshots",
                    },
                },
            ],
        }
        capabilities = helper.derive_runtime_capabilities(tree)
        self.assertEqual(
            capabilities["watchdog_services"],
            ["httpd.service", "nginx.service", "redis.service", "mysqld.service"],
        )
        self.assertTrue(capabilities["gatekeeper_secure_log"])
        self.assertIsNotNone(capabilities["wordpress"])
        self.assertTrue(capabilities["mcp_worker"])
        self.assertIn("/var/log/httpd", capabilities["log_read_scopes"])
        self.assertIn("/var/log/redis", capabilities["log_read_scopes"])
        self.assertIn("/var/log/secure", capabilities["log_read_files"])

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
        self.assertIn("MATRIX_RUNTIME_CAPABILITIES_B64=", command)
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
        with self.assertRaises(ValueError):
            helper.validate_runtime_capabilities({"arbitrary_sudo": True})

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
        self.assertIn(
            'rm -f "/etc/sudoers.d/matrixswarm-$SWARM_USER-watchdogs"',
            without_mcp,
        )
        self.assertIn(
            'gpasswd -d "$SWARM_USER" matrix-secure-readers',
            without_mcp,
        )
        self.assertIn("wordpress-acl", command)
        self.assertIn('SNAPSHOT_ROOT=/opt/swarm/guard/snapshots', command)
        self.assertIn('done < "$WP_ACL_MANIFEST"', without_mcp)

    def test_forensic_detective_gets_diagnostic_logs_but_not_kernel_or_root(self):
        helper = load_module(self.shell_helper_path, "forensic_capabilities")
        capabilities = helper.derive_runtime_capabilities({
            "name": "matrix",
            "children": [{"name": "forensic_detective", "config": {}}],
        })
        self.assertEqual(
            capabilities["log_read_scopes"],
            [
                "/var/log/apache2",
                "/var/log/httpd",
                "/var/log/nginx",
                "/var/log/mariadb",
                "/var/log/mysql",
                "/var/log/redis",
            ],
        )
        self.assertEqual(capabilities["log_read_files"], ["/var/log/mysqld.log"])
        grants = helper.describe_runtime_capabilities(capabilities)
        self.assertFalse(any("dmesg" in grant or "/root" in grant for grant in grants))

    def test_site_sentinel_receives_only_approved_read_only_log_scopes(self):
        helper = load_module(self.shell_helper_path, "site_sentinel_capabilities")
        tree = {
            "name": "matrix",
            "children": [{
                "name": "site_sentinel",
                "config": {
                    "traffic": {
                        "enabled": True,
                        "access_logs": [
                            "/var/log/httpd/access_log",
                            "/var/log/nginx/access.log",
                        ],
                    }
                },
            }],
        }
        capabilities = helper.derive_runtime_capabilities(tree)
        self.assertEqual(
            capabilities["log_read_scopes"],
            ["/var/log/httpd", "/var/log/nginx"],
        )
        self.assertEqual(capabilities["log_read_files"], [])
        self.assertEqual(
            helper.describe_runtime_capabilities(capabilities),
            ["READ /var/log/httpd/**", "READ /var/log/nginx/**"],
        )

        encoded = helper.encode_runtime_capability_manifest(capabilities)
        manifest = json.loads(base64.b64decode(encoded).decode("utf-8"))
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["grants"], [
            "READ /var/log/httpd/**",
            "READ /var/log/nginx/**",
        ])

        command = helper.build_remote_matrixd_command(
            action="start",
            universe="dragoart",
            linux_user="matrix-dragoart",
            runtime_capabilities=capabilities,
        )
        self.assertIn("setfacl -m", command)
        self.assertIn("[LOG-ACCESS] READ /var/log/httpd/**", command)
        self.assertNotIn("chmod 777", command)

        tree["children"][0]["config"]["traffic"]["access_logs"] = [
            "/root/private.log"
        ]
        with self.assertRaises(ValueError):
            helper.derive_runtime_capabilities(tree)

    def test_matrix_announces_railgun_managed_grants_at_boot(self):
        matrix_source = source(
            ROOT / "matrixos/agents/python_core/matrix/matrix.py"
        )
        self.assertIn("MATRIX_RUNTIME_CAPABILITIES_B64", matrix_source)
        self.assertIn("Railgun-managed active grants", matrix_source)
        self.assertIn("Universe-wide boundary", matrix_source)
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
        self.assertIn("--protect-memory", current.command)
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

    def test_root_only_memory_protection_is_wired_end_to_end(self):
        helper = load_module(self.shell_helper_path, "memory_protection_flag")
        command = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
            boot_flags=("--protect-memory",),
        )
        self.assertIn("--protect-memory", command)

        matrixd_source = source("matrixos/scripts/matrixd")
        spawner_source = source("matrixos/core/python_core/core_spawner.py")
        launcher_source = source("matrixos/core/python_core/protected_launcher.py")
        boot_source = source("matrixos/core/python_core/boot_agent.py")
        self.assertIn('"--protect-memory",', matrixd_source)
        self.assertIn("protected_launcher.py", spawner_source)
        self.assertNotIn('"-c"', spawner_source)
        self.assertIn("PR_SET_DUMPABLE", launcher_source)
        self.assertIn("runpy.run_path", launcher_source)
        self.assertIn("PR_GET_DUMPABLE did not confirm protection", boot_source)
        self.assertIn(
            "cp.set_protect_memory(self.memory_protection)", boot_source
        )

    def test_railgun_redeploy_replaces_an_active_universe(self):
        helper = load_module(self.shell_helper_path, "railgun_redeploy")
        command = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
            boot_flags=("--reboot-new",),
        )
        self.assertLess(
            command.index("matrixd kill --universe phoenix"),
            command.index("matrixd boot --universe phoenix"),
        )

        options_source = source(
            "phoenix/matrix_gui/modules/directive/deploy_options_dialog.py"
        )
        matrixd_source = source("matrixos/scripts/matrixd")
        self.assertIn("self.flag_reboot.setChecked(True)", options_source)
        self.assertIn(
            "args.reboot or args.reboot_new or args.reboot_id",
            matrixd_source,
        )
        self.assertIn(
            "[REBOOT][ABORT] Prior '{universe}' agents survived shutdown.",
            matrixd_source,
        )

    def test_protected_and_direct_agents_share_the_universe_kill_boundary(self):
        matrixd = load_matrixd("matrixd_protected_inventory")

        class FakeProcess:
            def __init__(self, pid, cmdline, environment=None):
                self.info = {"pid": pid, "cmdline": cmdline}
                self._environment = environment or {}

            def environ(self):
                return dict(self._environment)

        old_uid = "873adca8b378468c9de5a20f9026b85c"
        new_uid = "ceb670c1856f4812b3b9b62443f9cd36"
        old_run = (
            "/matrix/universes/runtime/phoenix/20260909_233000/"
            "pod/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/run"
        )
        new_run = (
            "/matrix/universes/runtime/phoenix/20260909_233300/"
            "pod/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/run"
        )
        processes = [
            FakeProcess(
                108928,
                ["/matrix/.venv/bin/python3", old_run, "--job", f"phoenix:{old_uid}"],
            ),
            FakeProcess(
                109272,
                [
                    "/matrix/.venv/bin/python3",
                    "/matrix/core/python_core/protected_launcher.py",
                    "--job",
                    f"phoenix:{new_uid}",
                ],
                {"MATRIX_AGENT_RUN_PATH": new_run},
            ),
            FakeProcess(
                109999,
                ["/tmp/protected_launcher.py", "--job", "phoenix:decoy"],
            ),
            FakeProcess(
                110000,
                [
                    "/matrix/.venv/bin/python3",
                    old_run.replace("/phoenix/", "/dragoart/"),
                    "--job",
                    "phoenix:mismatched",
                ],
            ),
        ]

        with mock.patch.object(matrixd.psutil, "process_iter", return_value=processes):
            agents = matrixd.get_all_swarm_agent_info(universe="phoenix")

        self.assertEqual([agent["pid"] for agent in agents], [108928, 109272])
        self.assertEqual(
            [agent["universal_id"] for agent in agents], [old_uid, new_uid]
        )
        self.assertEqual(
            [agent["reboot_uuid"] for agent in agents],
            ["20260909_233000", "20260909_233300"],
        )
        self.assertTrue(all(agent["comm_path"] for agent in agents))

    def test_universe_teardown_sudo_is_exact_and_universe_scoped(self):
        helper = load_module(self.shell_helper_path, "teardown_sudo_scope")
        command = helper.build_remote_matrixd_command(
            action="start",
            universe="phoenix",
            linux_user="matrix-phoenix",
            boot_flags=(),
        )

        delete_only = (
            "/matrix/.venv/bin/python3 /matrix/scripts/matrixd kill "
            "--universe phoenix --delete-directive-with-key"
        )
        full_cleanup = delete_only + " --clean-up"
        self.assertIn(delete_only, command)
        self.assertIn(full_cleanup, command)
        self.assertIn(
            "/etc/sudoers.d/matrixswarm-$SWARM_USER-teardown",
            command,
        )
        self.assertNotIn("NOPASSWD: ALL", command)
        self.assertNotIn("matrixd *", command)

        encoded = helper.encode_runtime_capability_manifest(
            {}, universe="phoenix"
        )
        manifest = json.loads(base64.b64decode(encoded).decode("utf-8"))
        self.assertIn(
            "SUDO teardown phoenix directive/key; optional runtime/static trees",
            manifest["grants"],
        )

        matrix_source = source("matrixos/agents/python_core/matrix/matrix.py")
        self.assertIn('cmd = [sudo, "-n"] + cmd', matrix_source)

    def test_boot_pruning_never_treats_persistent_state_as_a_boot(self):
        matrixd_source = source("matrixos/scripts/matrixd")
        tree = ast.parse(matrixd_source, filename="matrixos/scripts/matrixd")
        selected = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_prune_old_boots"
        ]
        namespace = {"shutil": shutil}
        exec(
            compile(
                ast.Module(body=selected, type_ignores=[]),
                "matrixd",
                "exec",
            ),
            namespace,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_boot = root / "20260914_010000"
            new_boot = root / "20260915_010000"
            persistent = root / "persistent"
            latest = root / "latest"
            for path in (old_boot, new_boot, persistent, latest):
                path.mkdir()
                (path / "marker").write_text(path.name, encoding="utf-8")

            self.assertTrue(namespace["_prune_old_boots"](root))
            self.assertFalse(old_boot.exists())
            self.assertTrue(new_boot.is_dir())
            self.assertTrue(persistent.is_dir())
            self.assertTrue((persistent / "marker").is_file())
            self.assertTrue(latest.is_dir())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux prctl test")
    def test_memory_bootstrap_remains_nondumpable_while_agent_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            probe = Path(temp_dir) / "probe.py"
            probe.write_text(
                "import ctypes\n"
                "print(ctypes.CDLL(None).prctl(3, 0, 0, 0, 0))\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["MATRIX_AGENT_RUN_PATH"] = str(probe)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "matrixos/core/python_core/protected_launcher.py"),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        self.assertEqual(result.stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()
