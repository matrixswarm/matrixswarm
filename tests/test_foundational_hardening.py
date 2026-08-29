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

    def test_core_requirements_do_not_include_sora_mysql_connector(self):
        requirements = source("matrixos/requirements.txt")
        self.assertNotIn("mysql-connector-python", requirements)

    def test_logger_source_never_prints_encrypted_payload(self):
        logger = source(
            "matrixos/core/python_core/class_lib/logging/logger.py"
        )
        self.assertNotIn(
            'console_mode == "json" or hasattr(self, "_decoded_swarm_key")',
            logger,
        )
        self.assertIn("print(json.dumps(log_entry", logger)

    def test_railgun_requires_python_312_for_new_environments(self):
        installer = source(
            "phoenix/matrix_gui/modules/railgun/railgun_install_dialog.py"
        )
        self.assertEqual(installer.count("command -v python3.12"), 2)
        self.assertEqual(
            installer.count('"$PYTHON_BIN" -m venv "$VENV_DIR"'), 2
        )
        self.assertEqual(
            installer.count('"$PYTHON_BIN" -m venv "$MCP_VENV"'), 2
        )
        self.assertNotIn("python3 -m venv \"$VENV_DIR\"", installer)
        self.assertIn("refusing the system python fallback", installer)

    def test_railgun_installs_dependencies_on_rocky_and_debian(self):
        installer = source(
            "phoenix/matrix_gui/modules/railgun/railgun_install_dialog.py"
        )
        self.assertEqual(installer.count("install_os_packages()"), 2)
        self.assertEqual(installer.count("command -v dnf"), 2)
        self.assertEqual(installer.count("command -v apt-get"), 2)
        self.assertEqual(installer.count("command -v setfacl"), 2)
        self.assertIn("install_os_packages rsync sudo acl", installer)
        self.assertIn(
            "install_os_packages git rsync util-linux sudo acl",
            installer,
        )

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
