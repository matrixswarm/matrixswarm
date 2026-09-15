import base64
import importlib.util
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MATRIXOS = ROOT / "matrixos"
if str(MATRIXOS) not in sys.path:
    sys.path.insert(0, str(MATRIXOS))

from core.python_core.utils.systemd_service import (
    diagnostic_command,
    restart_command,
    status_command,
)

CLOCK_VALIDATION = ROOT / "phoenix/matrix_gui/modules/railgun/clock_validation.py"
clock_spec = importlib.util.spec_from_file_location(
    "railgun_clock_validation",
    CLOCK_VALIDATION,
)
clock_validation = importlib.util.module_from_spec(clock_spec)
clock_spec.loader.exec_module(clock_validation)

try:
    from core.python_core.class_lib.logging.logger import Logger
except ModuleNotFoundError as error:
    if error.name != "Crypto":
        raise
    Logger = None


def source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class FoundationalHardeningTests(unittest.TestCase):
    @unittest.skipIf(Logger is None, "PyCryptodome is not installed")
    def test_encrypted_logger_keeps_ciphertext_off_stdout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = Logger(temp_dir)
            logger.set_encryption_key(
                base64.b64encode(b"x" * 32).decode("ascii")
            )

            console = io.StringIO()
            with redirect_stdout(console):
                logger.log({"event": "boot", "token": "super-secret"})

            rendered = console.getvalue()
            self.assertIn("boot", rendered)
            self.assertIn("[REDACTED]", rendered)
            self.assertNotIn("super-secret", rendered)

            encrypted = Path(logger.default_log_file).read_text(
                encoding="utf-8"
            ).strip()
            self.assertNotIn("boot", encrypted)
            self.assertGreater(len(base64.b64decode(encrypted)), 28)

    def test_watchdog_commands_match_the_narrow_sudoers_contract(self):
        self.assertEqual(
            status_command("httpd"),
            ["/usr/bin/systemctl", "is-active", "--quiet", "httpd.service"],
        )
        self.assertEqual(
            restart_command("mysqld"),
            [
                "/usr/bin/sudo",
                "-n",
                "/usr/bin/systemctl",
                "restart",
                "mysqld.service",
            ],
        )
        self.assertEqual(
            diagnostic_command("redis"),
            [
                "/usr/bin/systemctl",
                "status",
                "--no-pager",
                "redis.service",
            ],
        )
        nginx = source(
            "matrixos/agents/python_core/nginx_watchdog/nginx_watchdog.py"
        )
        self.assertIn("restart_command(self.service_name)", nginx)
        self.assertNotIn(
            '["systemctl", "restart", self.service_name]',
            nginx,
        )

    def test_core_requirements_do_not_include_sora_mysql_connector(self):
        requirements = source("matrixos/requirements.txt")
        self.assertNotIn("mysql-connector-python", requirements)

    def test_runtime_requirements_exclude_unused_data_science_stack(self):
        for requirements_path in (
            "matrixos/requirements.txt",
            "phoenix/requirements.txt",
        ):
            requirements = source(requirements_path).lower()
            self.assertNotIn("numpy", requirements)
            self.assertNotIn("pandas", requirements)
            self.assertNotIn("pytrends", requirements)

    def test_logger_source_never_prints_encrypted_payload(self):
        logger = source(
            "matrixos/core/python_core/class_lib/logging/logger.py"
        )
        self.assertNotIn(
            'console_mode == "json" or hasattr(self, "_decoded_swarm_key")',
            logger,
        )
        self.assertIn("print(json.dumps(log_entry", logger)

    def test_agent_arms_encrypted_logger_before_first_structured_log(self):
        boot_agent = source("matrixos/core/python_core/boot_agent.py")
        key_activation = boot_agent.index(
            "self.logger.set_encryption_key(self.swarm_key)"
        )
        first_agent_log = boot_agent.index('"[BOOT][MEMORY] protected:')
        self.assertLess(key_activation, first_agent_log)

    def test_log_streamer_accepts_legacy_plaintext_structured_records(self):
        streamer = source(
            "matrixos/agents/python_core/log_streamer/log_streamer.py"
        )
        self.assertIn("entry = json.loads(candidate)", streamer)
        self.assertIn("candidate = Logger.decrypt_log_line", streamer)
        self.assertIn('rendered.append(f"[MALFORMED] {candidate}")', streamer)

    def test_railgun_requires_python_312_for_new_environments(self):
        installer = source(
            "phoenix/matrix_gui/modules/railgun/railgun_install_dialog.py"
        )
        # Each installer probes once, then probes again after optional package
        # provisioning before it permits the isolated environment to exist.
        self.assertEqual(installer.count("command -v python3.12"), 4)
        self.assertEqual(
            installer.count('"$PYTHON_BIN" -m venv "$VENV_DIR"'), 2
        )
        self.assertEqual(
            installer.count('"$PYTHON_BIN" -m venv "$MCP_VENV"'), 2
        )
        self.assertNotIn("python3 -m venv \"$VENV_DIR\"", installer)
        self.assertIn("refusing the system python fallback", installer)
        self.assertEqual(
            installer.count(
                "Python 3.12 not found; provisioning it from the OS package manager"
            ),
            2,
        )
        self.assertEqual(
            installer.count("dnf install -y python3.12 python3.12-pip"),
            2,
        )
        self.assertEqual(
            installer.count("python3.12 python3.12-venv"),
            2,
        )

    def test_railgun_installs_dependencies_on_rocky_and_debian(self):
        installer = source(
            "phoenix/matrix_gui/modules/railgun/railgun_install_dialog.py"
        )
        self.assertEqual(installer.count("install_os_packages()"), 2)
        self.assertEqual(installer.count("command -v dnf"), 4)
        self.assertEqual(installer.count("command -v apt-get"), 4)
        self.assertEqual(installer.count("command -v setfacl"), 2)
        self.assertIn("install_os_packages rsync sudo acl", installer)
        self.assertIn(
            "install_os_packages git rsync util-linux sudo acl",
            installer,
        )
        self.assertEqual(installer.count("dnf install -y openssh-clients"), 2)
        self.assertEqual(installer.count("apt-get install -y openssh-client"), 2)
        self.assertEqual(installer.count("install_os_packages sshpass"), 2)
        self.assertEqual(
            installer.count("sed -i 's/\\\\r$//' \"$MCP_LAUNCHER\""),
            2,
        )

    def test_railgun_root_locks_shared_source_and_universe_parents(self):
        installer = source(
            "phoenix/matrix_gui/modules/railgun/railgun_install_dialog.py"
        )
        self.assertEqual(installer.count("harden_matrix_install() {{"), 2)
        self.assertEqual(
            installer.count('chown -hR root:root "$SOURCE_PATH"'),
            2,
        )
        self.assertEqual(
            installer.count('setfacl -R -P -b -- "$SOURCE_PATH"'),
            2,
        )
        self.assertEqual(
            installer.count(
                'find "$SOURCE_PATH" -xdev -type f '
                '-exec chmod a+r,go-w {{}} +'
            ),
            2,
        )
        self.assertEqual(
            installer.count(
                'chmod 0711 "$TARGET/universes" "$TARGET/universes/runtime"'
            ),
            2,
        )
        self.assertEqual(
            installer.count(
                '"$TARGET/teams" "$TARGET/.venv" "$TARGET/mcp/.venv"'
            ),
            2,
        )
        self.assertEqual(
            installer.count(
                'install -d -o root -g root -m 0711 "$TARGET/mcp/workers"'
            ),
            2,
        )
        # Runtime data remains mutable and is protected by its outer boundary;
        # it must never be recursively converted into root-owned source.
        self.assertNotIn(
            'chown -hR root:root "$TARGET/universes"',
            installer,
        )

    def test_railgun_drains_final_installer_diagnostics(self):
        installer = source(
            "phoenix/matrix_gui/modules/railgun/railgun_install_dialog.py"
        )
        exit_check = installer.index("channel.exit_status_ready()")
        stdout_drain = installer.rindex(
            "while channel.recv_ready():",
            0,
            exit_check,
        )
        stderr_drain = installer.rindex(
            "while channel.recv_stderr_ready():",
            0,
            exit_check,
        )
        self.assertLess(stdout_drain, exit_check)
        self.assertLess(stderr_drain, exit_check)

    def test_railgun_remote_check_does_not_block_or_switch_targets(self):
        checker = source(
            "phoenix/matrix_gui/modules/railgun/railgun_check_dialog.py"
        )
        self.assertIn("class RailgunCheckWorker(QThread)", checker)
        self.assertIn("timeout=self.COMMAND_TIMEOUT", checker)
        self.assertIn("Qt.ItemDataRole.UserRole + 1", checker)
        self.assertIn(
            "[FAIL] Recon aborted; no remote checks were executed.",
            checker,
        )
        self.assertNotIn(
            "self.refresh_targets()\n"
            "        self.output_box.append(\"\\n⚡ <b>Running Full Recon",
            checker,
        )
        self.assertNotIn(
            "self.check_ssh()\n"
            "        self.check_os()\n"
            "        self.check_python()",
            checker,
        )

    def test_railgun_clock_check_requires_ntp_and_bounded_skew(self):
        remote_iso, skew = clock_validation.validate_remote_clock(
            "1000|yes|1970-01-01T00:16:40Z",
            1010,
        )
        self.assertEqual(remote_iso, "1970-01-01T00:16:40Z")
        self.assertEqual(skew, 10)

        with self.assertRaisesRegex(ValueError, "not synchronized"):
            clock_validation.validate_remote_clock(
                "1000|no|1970-01-01T00:16:40Z",
                1010,
            )

        with self.assertRaisesRegex(ValueError, "clock skew is 121s"):
            clock_validation.validate_remote_clock(
                "1000|yes|1970-01-01T00:16:40Z",
                1121,
            )

    def test_log_streamer_keeps_session_when_any_relay_is_fresh(self):
        streamer = source(
            "matrixos/agents/python_core/log_streamer/log_streamer.py"
        )
        self.assertIn("def _relay_status_for_session", streamer)
        self.assertIn("if fresh_relays:", streamer)
        self.assertIn("if relay_count == 0:", streamer)
        self.assertIn("No fresh relays remain", streamer)


if __name__ == "__main__":
    unittest.main()
