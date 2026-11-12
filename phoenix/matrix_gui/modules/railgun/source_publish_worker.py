"""Publish a server-wide agent source via its pinned administrator SSH profile."""
import hashlib
import json
import re
import shlex
import time
from copy import deepcopy

from PyQt6.QtCore import QThread, pyqtSignal
from matrix_gui.modules.railgun.ssh_support import connect_ssh_profile

MAX_SOURCE_BYTES = 4 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}\Z")


def _publisher_preflight(*, _base="/matrix", _admin_uid=0):
    """Fixed shell preflight runs as root before importing MatrixOS code.

    The private arguments support isolated, unprivileged fixture tests; the
    worker always uses the fixed production defaults.
    """
    base = shlex.quote(_base)
    uid = int(_admin_uid)
    return f'''set -eu
fail() {{ printf '%s\\n' "$1" >&2; exit 77; }}
check_owned() {{
    [ ! -L "$1" ] || fail "Refusing linked administrator path"
    owner=$(/usr/bin/stat -c %u -- "$1") || fail "Cannot inspect administrator path"
    mode=$(/usr/bin/stat -c %a -- "$1") || fail "Cannot inspect administrator mode"
    [ "$owner" = "$2" ] || fail "Untrusted administrator path owner"
    [ $((0$mode & 022)) -eq 0 ] || fail "Writable administrator path"
}}
[ "$(/usr/bin/id -u)" -eq {uid} ] || fail "Publisher requires administrator privileges"
base={base}
check_owned / 0
check_owned "$base" {uid}
check_owned "$base/scripts" {uid}
check_owned "$base/core" {uid}
publisher="$base/scripts/matrix_source_publish.py"
[ -f "$publisher" ] || fail "Source publisher is missing"
check_owned "$publisher" {uid}
[ "$(/usr/bin/stat -c %h -- "$publisher")" -eq 1 ] || fail "Refusing linked source publisher"
bad=$(/usr/bin/find -P "$base/core" -xdev \\( -type l -o \\( ! -type d -a ! -type f \\) -o ! -uid {uid} -o -perm /022 -o \\( -type f -links +1 \\) \\) -print -quit) || fail "Cannot inspect core source tree"
[ -z "$bad" ] || fail "Untrusted core source tree"
/usr/bin/awk -v core="$base/core" -v scripts="$base/scripts" -v venv="$base/.venv" \
    '$5 == core || index($5, core "/") == 1 || $5 == scripts || index($5, scripts "/") == 1 || $5 == venv || index($5, venv "/") == 1 {{ exit 1 }}' \
    /proc/self/mountinfo || fail "Mounted source or interpreter path is not permitted"
check_owned /usr 0
check_owned /usr/bin 0
python=$(/usr/bin/readlink -e /usr/bin/python3) || fail "System Python is unavailable"
[ -f "$python" ] || fail "System Python is unavailable"
check_chain() {{
    item=$1
    while :; do
        check_owned "$item" 0
        [ "$item" = / ] && break
        item=${{item%/*}}
        [ -n "$item" ] || item=/
    done
}}
check_chain "$python"
check_owned "$base/.venv" {uid}
check_owned "$base/.venv/bin" {uid}
target="$base/.venv/bin/python3"
[ -e "$target" ] || fail "MatrixOS Python is unavailable"
if [ -L "$target" ]; then
    [ "$(/usr/bin/stat -c %u -- "$target")" = "{uid}" ] || fail "Untrusted Python link owner"
else
    check_owned "$target" {uid}
fi
target_real=$(/usr/bin/readlink -e "$target") || fail "Cannot resolve MatrixOS Python"
check_chain "$target_real"
exec /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C "$python" -I -S "$publisher" "$@"
'''


class SourcePublishWorker(QThread):
    result = pyqtSignal(object, object)

    def __init__(self, profile, agent_name, source):
        super().__init__()
        self.profile = deepcopy(profile)
        self.agent_name = agent_name
        self.source = bytes(source)

    def run(self):
        client = channel = None
        dispatched = False
        try:
            if not _NAME.fullmatch(self.agent_name) or not 0 < len(self.source) <= MAX_SOURCE_BYTES:
                raise ValueError("Invalid agent name or source size")
            digest = hashlib.sha256(self.source).hexdigest()
            client, _ = connect_ssh_profile(self.profile)
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise RuntimeError("SSH connection is unavailable")
            channel = transport.open_session(timeout=15)
            channel.settimeout(30)
            prefix = "" if str(self.profile.get("username", "")).strip() == "root" else "sudo -n -- "
            command = (prefix + "/bin/sh -c " + shlex.quote(_publisher_preflight())
                       + " -- --agent " + shlex.quote(self.agent_name)
                       + " --sha256 " + shlex.quote(digest))
            dispatched = True
            channel.exec_command(command)
            channel.sendall(self.source)
            channel.shutdown_write()
            out = bytearray()
            err = bytearray()
            deadline = time.monotonic() + 45
            while True:
                if channel.recv_ready():
                    out.extend(channel.recv(4096))
                if channel.recv_stderr_ready():
                    err.extend(channel.recv_stderr(4096))
                if len(out) > 16384 or len(err) > 16384:
                    raise RuntimeError("Unexpectedly large publisher response")
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Publisher response timed out")
                time.sleep(0.02)
            status = channel.recv_exit_status()
            if status != 0:
                try:
                    error = json.loads(err.decode("utf-8"))
                    detail = str(error.get("message") or "Publisher rejected the request")
                except (ValueError, UnicodeError, AttributeError):
                    detail = "Publisher rejected the request; check administrator access and server installation"
                raise RuntimeError(detail)
            result = json.loads(out.decode("utf-8"))
            if (not isinstance(result, dict) or result.get("status") != "success"
                    or result.get("agent") != self.agent_name or result.get("sha256") != digest):
                raise RuntimeError("Publisher confirmation did not match the requested source")
            self.result.emit(result, None)
        except Exception as exc:
            outcome = "Server outcome may be unknown; inspect the source before retrying." if dispatched else "No source publication was requested."
            self.result.emit(None, f"{type(exc).__name__}: {exc}. {outcome}")
        finally:
            for resource in (channel, client):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass
            self.profile = None
            self.source = b""
