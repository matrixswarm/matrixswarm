"""Open an existing ingress inbox using the SSH account's current authority."""

import errno

import paramiko


# Fixed system paths only. No inbox, packet, or profile value becomes shell text.
# sudo -n uses an existing grant and fails instead of prompting for a password.
_SUDO_SFTP_COMMAND = (
    'for server in /usr/lib/openssh/sftp-server '
    '/usr/libexec/openssh/sftp-server /usr/lib/ssh/sftp-server; do '
    'if [ -x "$server" ]; then exec sudo -n -- "$server"; fi; '
    'done; printf "%s\\n" "No supported SFTP server executable found" >&2; exit 127'
)


def _close_quietly(resource):
    if resource is not None:
        try:
            resource.close()
        except Exception:
            pass


def open_inbox_sftp(client, inbox, *, timeout=15):
    """Return (SFTP client, used_sudo) after verifying the inbox is accessible.

    The caller must already have authenticated with a verified host key. Ordinary
    SFTP is preferred; only an explicit permission denial triggers elevation.
    Missing inboxes and network errors retain their original diagnostics.
    """
    direct = None
    try:
        direct = client.open_sftp()
        direct.get_channel().settimeout(timeout)
        direct.stat(inbox)
        return direct, False
    except OSError as exc:
        _close_quietly(direct)
        if exc.errno not in (errno.EACCES, errno.EPERM):
            raise
    except Exception:
        _close_quietly(direct)
        raise

    channel = elevated = None
    try:
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise ConnectionError("SSH transport closed before inbox elevation")
        channel = transport.open_session(timeout=timeout)
        channel.settimeout(timeout)
        # No PTY: the channel must carry the binary SFTP protocol unchanged.
        channel.exec_command(_SUDO_SFTP_COMMAND)
        elevated = paramiko.SFTPClient(channel)
        elevated.stat(inbox)
        return elevated, True
    except Exception as exc:
        _close_quietly(elevated)
        _close_quietly(channel)
        raise PermissionError(
            "SSH inbox access was denied and passwordless sudo SFTP could not "
            "be opened. Use an SSH account that owns the universe inbox or has "
            "an existing passwordless sudo grant for the system sftp-server. "
            f"Elevation failed ({type(exc).__name__})."
        ) from exc
