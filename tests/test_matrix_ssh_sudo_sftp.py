"""Exercise inbox permission failures without credentials or a remote server."""

import errno
import importlib.util
from pathlib import Path
import socket
import unittest
from unittest.mock import Mock, patch


PATH = Path(__file__).resolve().parents[1] / (
    "phoenix/matrix_gui/modules/net/connector/egress/ssh_sftp.py"
)
SPEC = importlib.util.spec_from_file_location("matrix_ssh_sudo_sftp_tested", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InboxSFTPTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.direct = self.client.open_sftp.return_value
        self.transport = self.client.get_transport.return_value
        self.transport.is_active.return_value = True
        self.channel = self.transport.open_session.return_value
        self.inbox = "/matrix/universes/static/phoenix/persistent/matrix-ssh-a/comm/incoming"

    def test_accessible_inbox_uses_direct_sftp_without_elevation(self):
        sftp, elevated = MODULE.open_inbox_sftp(self.client, self.inbox, timeout=7)
        self.assertIs(sftp, self.direct)
        self.assertFalse(elevated)
        self.direct.stat.assert_called_once_with(self.inbox)
        self.direct.get_channel.return_value.settimeout.assert_called_once_with(7)
        self.client.get_transport.assert_not_called()
        self.direct.close.assert_not_called()

    def test_denied_inbox_uses_existing_sudo_grant_on_the_same_transport(self):
        self.direct.stat.side_effect = PermissionError(errno.EACCES, "Permission denied")
        with patch.object(MODULE.paramiko, "SFTPClient") as factory:
            sftp, elevated = MODULE.open_inbox_sftp(self.client, self.inbox, timeout=7)
        self.assertTrue(elevated)
        self.assertIs(sftp, factory.return_value)
        self.direct.close.assert_called_once()
        self.transport.open_session.assert_called_once_with(timeout=7)
        self.channel.settimeout.assert_called_once_with(7)
        self.channel.exec_command.assert_called_once_with(MODULE._SUDO_SFTP_COMMAND)
        self.channel.get_pty.assert_not_called()
        factory.assert_called_once_with(self.channel)
        sftp.stat.assert_called_once_with(self.inbox)
        self.channel.close.assert_not_called()
        self.assertIn("sudo -n --", MODULE._SUDO_SFTP_COMMAND)
        self.assertNotIn(self.inbox, MODULE._SUDO_SFTP_COMMAND)

    def test_missing_inbox_and_connection_errors_do_not_trigger_sudo(self):
        for error in (FileNotFoundError(errno.ENOENT, "missing"),
                      OSError(errno.ECONNRESET, "reset"), socket.timeout("timed out")):
            with self.subTest(error=type(error).__name__):
                self.client.reset_mock()
                self.direct.stat.side_effect = error
                with self.assertRaises(type(error)) as caught:
                    MODULE.open_inbox_sftp(self.client, self.inbox)
                self.assertIs(caught.exception, error)
                self.direct.close.assert_called_once()
                self.client.get_transport.assert_not_called()

    def test_sudo_denial_and_handshake_timeout_close_channel_and_explain_failure(self):
        self.direct.stat.side_effect = PermissionError(errno.EACCES, "denied")
        for error in (EOFError("sudo refused"), socket.timeout("handshake timed out")):
            with self.subTest(error=type(error).__name__):
                self.channel.reset_mock()
                with patch.object(MODULE.paramiko, "SFTPClient", side_effect=error):
                    with self.assertRaisesRegex(PermissionError, "passwordless sudo SFTP"):
                        MODULE.open_inbox_sftp(self.client, self.inbox)
                self.channel.close.assert_called_once()

    def test_failed_elevated_inbox_check_closes_sftp_and_channel(self):
        self.direct.stat.side_effect = PermissionError(errno.EACCES, "denied")
        with patch.object(MODULE.paramiko, "SFTPClient") as factory:
            factory.return_value.stat.side_effect = FileNotFoundError(errno.ENOENT, "missing")
            with self.assertRaises(PermissionError):
                MODULE.open_inbox_sftp(self.client, self.inbox)
            factory.return_value.close.assert_called_once()
        self.channel.close.assert_called_once()

    def test_closed_transport_does_not_attempt_elevation(self):
        self.direct.stat.side_effect = PermissionError(errno.EACCES, "denied")
        self.transport.is_active.return_value = False
        with self.assertRaisesRegex(PermissionError, "ConnectionError"):
            MODULE.open_inbox_sftp(self.client, self.inbox)
        self.transport.open_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
