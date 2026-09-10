"""Fail-closed builders for MatrixOS SSH launch commands."""

import base64
import hashlib
import json
import posixpath
import re
import shlex


_SAFE_REMOTE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_LINUX_USER = re.compile(r"[a-z_][a-z0-9_-]{0,30}\Z")
_ALLOWED_BOOT_FLAGS = {
    "--clean",
    "--debug",
    "--reboot",
    "--reboot-new",
    "--rug-pull",
    "--protect-memory",
}
_WATCHDOG_SERVICE_BY_AGENT = {
    "apache_watchdog": "httpd",
    "nginx_watchdog": "nginx",
    "redis_watchdog": "redis",
    "mysql_watchdog": "mysqld",
}
_ALLOWED_WATCHDOG_UNITS = {
    "apache2.service",
    "httpd.service",
    "mariadb.service",
    "mysqld.service",
    "nginx.service",
    "redis.service",
}
_ALLOWED_LOG_SCOPE_ROOTS = (
    "/var/log/apache2",
    "/var/log/httpd",
    "/var/log/mariadb",
    "/var/log/mysql",
    "/var/log/nginx",
    "/var/log/redis",
)
_ALLOWED_EXACT_LOG_FILES = {
    "/var/log/auth.log",
    "/var/log/dovecot.log",
    "/var/log/fail2ban.log",
    "/var/log/maillog",
    "/var/log/messages",
    "/var/log/mysqld.log",
    "/var/log/secure",
}
_WATCHDOG_LOG_TARGETS = {
    "apache_watchdog": ("/var/log/apache2", "/var/log/httpd"),
    "nginx_watchdog": ("/var/log/nginx",),
    "mysql_watchdog": (
        "/var/log/mariadb",
        "/var/log/mysql",
        "/var/log/mysqld.log",
    ),
    "redis_watchdog": ("/var/log/redis",),
}
_FORENSIC_LOG_TARGETS = tuple(
    dict.fromkeys(
        path
        for targets in _WATCHDOG_LOG_TARGETS.values()
        for path in targets
    )
)
_RUNTIME_CAPABILITY_FIELDS = {
    "watchdog_services",
    "gatekeeper_secure_log",
    "wordpress",
    "mcp_worker",
    "log_read_scopes",
    "log_read_files",
}
MAX_BOOT_ENVELOPE_BYTES = 16 * 1024 * 1024
_BOOT_BUNDLE_FIELDS = {"nonce", "tag", "ciphertext"}
_MATRIXD_STDIN_PROBE = (
    "HELP=$(/matrix/.venv/bin/python3 /matrix/scripts/matrixd boot --help 2>&1); "
    "if printf '%s' \"$HELP\" | grep -F -- '--directive-stdin' >/dev/null "
    "&& printf '%s' \"$HELP\" | grep -F -- '--protect-memory' >/dev/null; "
    "then exit 0; else exit 65; fi"
)


def encode_boot_envelope(encrypted_bundle, swarm_key_b64):
    """Serialize one bounded, encrypted MatrixD boot payload for SSH stdin."""
    if not isinstance(encrypted_bundle, dict):
        raise ValueError("Encrypted directive bundle must be an object")
    if set(encrypted_bundle) != _BOOT_BUNDLE_FIELDS:
        raise ValueError("Encrypted directive bundle has unexpected fields")
    for field in sorted(_BOOT_BUNDLE_FIELDS):
        value = encrypted_bundle.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Encrypted directive {field} is required")
        try:
            base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError(
                f"Encrypted directive {field} is not valid Base64"
            ) from error

    key_text = str(swarm_key_b64 or "").strip()
    try:
        decoded_key = base64.b64decode(key_text, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("Vault swarm key is not valid Base64") from error
    if not 16 <= len(decoded_key) <= 64:
        raise ValueError("Vault swarm key has an invalid length")

    payload = json.dumps(
        {
            "version": 1,
            "encrypted_bundle": encrypted_bundle,
            "swarm_key": key_text,
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    if len(payload) > MAX_BOOT_ENVELOPE_BYTES:
        raise ValueError("Encrypted boot envelope exceeds the 16 MiB limit")
    return payload


def send_boot_envelope(channel, encrypted_bundle, swarm_key_b64):
    """Send a boot envelope once, then close only the SSH write direction."""
    payload = encode_boot_envelope(encrypted_bundle, swarm_key_b64)
    channel.sendall(payload)
    channel.shutdown_write()
    return len(payload)


def verify_remote_matrixd_stdin(client, timeout=30):
    """Fail before secret transfer when remote MatrixD lacks sealed stdin boot."""
    _stdin, stdout, stderr = client.exec_command(
        _MATRIXD_STDIN_PROBE, timeout=timeout
    )
    output = stdout.read(4_097)
    error = stderr.read(4_097)
    status = stdout.channel.recv_exit_status()
    if len(output) > 4_096 or len(error) > 4_096:
        raise RuntimeError("Remote MatrixD capability probe exceeded its limit")
    if status != 0:
        raise RuntimeError(
            "Remote MatrixOS update required: matrixd does not support "
            "sealed --directive-stdin and --protect-memory boot"
        )
    return True


def validate_remote_token(value, label):
    """Return a conservative command token or reject it before SSH use."""
    cleaned = str(value or "").strip()
    if not _SAFE_REMOTE_TOKEN.fullmatch(cleaned):
        raise ValueError(
            f"{label} must contain only letters, numbers, '.', '_', or '-' "
            "and be no longer than 128 characters"
        )
    return cleaned


def quote_remote_argument(value, label):
    """Validate required shell data and return its POSIX-quoted form."""
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if any(control in cleaned for control in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} contains a forbidden control character")
    return shlex.quote(cleaned)


def validate_linux_user(value, label="Linux user"):
    """Validate a conservative, non-root Linux service-account name."""
    cleaned = str(value or "").strip()
    if not _SAFE_LINUX_USER.fullmatch(cleaned):
        raise ValueError(
            f"{label} must start with a lowercase letter or '_', contain only "
            "lowercase letters, numbers, '_' or '-', and be at most 31 characters"
        )
    if not cleaned.startswith("matrix-"):
        raise ValueError(f"{label} must be a dedicated 'matrix-' service account")
    return cleaned


def default_linux_user(universe):
    """Create a stable service-account suggestion from a universe name."""
    universe = validate_remote_token(universe, "Universe name")
    slug = re.sub(r"[^a-z0-9_-]+", "-", universe.lower()).strip("-_")
    if not slug:
        slug = "universe"
    candidate = f"matrix-{slug}"
    if len(candidate) > 31:
        digest = hashlib.sha256(universe.encode("utf-8")).hexdigest()[:6]
        candidate = f"{candidate[:24].rstrip('-_')}-{digest}"
    return validate_linux_user(candidate)


def _walk_agent_nodes(node):
    """Yield agent dictionaries from a compiled directive tree."""
    if isinstance(node, dict):
        if node.get("name"):
            yield node
        for value in node.values():
            yield from _walk_agent_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_agent_nodes(value)


def _systemd_unit(value):
    """Return a sudoers-safe systemd unit from the strict watchdog allowlist."""
    unit = str(value or "").strip()
    if not unit.endswith(".service"):
        unit += ".service"
    if unit not in _ALLOWED_WATCHDOG_UNITS:
        raise ValueError(f"Unsupported watchdog systemd unit: {unit}")
    return unit


def _managed_path(value, label, allowed_root):
    """Validate an absolute capability path beneath one fixed system root."""
    cleaned = str(value or "").strip()
    if not cleaned or any(ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"{label} is required and must not contain controls")
    normalized = posixpath.normpath(cleaned)
    root = posixpath.normpath(allowed_root)
    if not normalized.startswith(root.rstrip("/") + "/"):
        raise ValueError(f"{label} must be beneath {root}")
    return normalized


def _log_read_target(value, label="Log path"):
    """Map one configured log path to a bounded directory scope or exact file."""
    cleaned = str(value or "").strip()
    if not cleaned or any(ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"{label} is required and must not contain controls")
    normalized = posixpath.normpath(cleaned)
    if not normalized.startswith("/"):
        raise ValueError(f"{label} must be an absolute path")
    for root in _ALLOWED_LOG_SCOPE_ROOTS:
        if normalized == root or normalized.startswith(root + "/"):
            return "scope", root
    if normalized in _ALLOWED_EXACT_LOG_FILES:
        return "file", normalized
    raise ValueError(
        f"{label} is outside the approved service-log allowlist: {normalized}"
    )


def _append_log_target(scopes, files, value, label="Log path"):
    kind, path = _log_read_target(value, label)
    target = scopes if kind == "scope" else files
    if path not in target:
        target.append(path)


def describe_runtime_capabilities(capabilities):
    """Return stable, non-secret descriptions of Railgun-managed grants."""
    data = validate_runtime_capabilities(capabilities)
    grants = []
    for unit in data["watchdog_services"]:
        grants.append(f"SUDO restart {unit}")
    if data["gatekeeper_secure_log"]:
        grants.append("READ SSH authentication log")
    for path in data["log_read_scopes"]:
        grants.append(f"READ {path}/**")
    for path in data["log_read_files"]:
        if path not in {"/var/log/secure", "/var/log/auth.log"} or not data["gatekeeper_secure_log"]:
            grants.append(f"READ {path}")
    wordpress = data["wordpress"]
    if wordpress:
        grants.extend((
            f"READ/WRITE {wordpress['plugin_dir']}/**",
            f"READ/WRITE {wordpress['quarantine_dir']}/**",
            f"READ/WRITE {wordpress['snapshot_root']}/**",
        ))
    if data["mcp_worker"]:
        grants.append("SUDO fixed matrix-mcp-launch wrapper (isolated account)")
    return grants


def describe_universe_teardown_grant(universe):
    """Describe the exact control-plane cleanup grant for one universe."""
    universe = validate_remote_token(universe, "Universe name")
    return (
        f"SUDO teardown {universe} directive/key; optional runtime/static trees"
    )


def encode_runtime_capability_manifest(capabilities, *, universe=None):
    """Encode a public capability attestation for Matrix's boot log."""
    grants = describe_runtime_capabilities(capabilities)
    if universe is not None:
        grants.append(describe_universe_teardown_grant(universe))
    payload = json.dumps(
        {"version": 1, "grants": grants},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def derive_runtime_capabilities(agent_tree):
    """Derive the least privileges required by enabled agents in a directive."""
    services = []
    gatekeeper_secure_log = False
    wordpress = None
    mcp_worker = False
    log_read_scopes = []
    log_read_files = []

    for node in _walk_agent_nodes(agent_tree):
        if node.get("enabled") is False:
            continue
        name = node.get("name")
        config = node.get("config") or {}

        if name in _WATCHDOG_SERVICE_BY_AGENT:
            service = config.get(
                "service_name", _WATCHDOG_SERVICE_BY_AGENT[name]
            )
            unit = _systemd_unit(service)
            if unit not in services:
                services.append(unit)
            for path in _WATCHDOG_LOG_TARGETS.get(name, ()):
                _append_log_target(
                    log_read_scopes,
                    log_read_files,
                    path,
                    f"{name} diagnostic log",
                )
        elif name == "gatekeeper":
            gatekeeper_secure_log = True
            for path in (
                config.get("log_path"),
                "/var/log/secure",
                "/var/log/auth.log",
            ):
                if path:
                    _append_log_target(
                        log_read_scopes,
                        log_read_files,
                        path,
                        "Gatekeeper log path",
                    )
        elif name == "site_sentinel":
            traffic = config.get("traffic") or {}
            if traffic.get("enabled", True):
                for path in traffic.get("access_logs", ()):
                    _append_log_target(
                        log_read_scopes,
                        log_read_files,
                        path,
                        "Site Sentinel access log",
                    )
        elif name == "log_health":
            path = config.get("log_path")
            if path:
                _append_log_target(
                    log_read_scopes,
                    log_read_files,
                    path,
                    "Log Health path",
                )
        elif name == "log_watcher":
            collectors = config.get("collectors") or {}
            if isinstance(collectors, dict):
                for collector_name, collector in collectors.items():
                    if not isinstance(collector, dict):
                        continue
                    for path in collector.get("paths", ()):
                        _append_log_target(
                            log_read_scopes,
                            log_read_files,
                            path,
                            f"Log Watcher {collector_name} path",
                        )
        elif name == "forensic_detective":
            # The detective dynamically selects a service investigator from
            # incoming reports, so its bounded maximum is every supported
            # service-log family. Kernel dmesg remains deliberately ungranted.
            for path in _FORENSIC_LOG_TARGETS:
                _append_log_target(
                    log_read_scopes,
                    log_read_files,
                    path,
                    "Forensic Detective diagnostic log",
                )
        elif name == "wordpress_plugin_guard":
            wordpress = {
                "plugin_dir": _managed_path(
                    config.get(
                        "plugin_dir",
                        "/var/www/html/wordpress/wp-content/plugins",
                    ),
                    "WordPress plugin directory",
                    "/var/www",
                ),
                "quarantine_dir": _managed_path(
                    config.get("quarantine_dir", "/opt/quarantine/wp_plugins"),
                    "WordPress quarantine directory",
                    "/opt/quarantine",
                ),
                "snapshot_root": _managed_path(
                    config.get(
                        "snapshot_root",
                        "/opt/swarm/guard/snapshots",
                    ),
                    "WordPress snapshot root",
                    "/opt/swarm",
                ),
            }
        elif name == "mcp_reflex":
            mcp_worker = True

    return {
        "watchdog_services": services,
        "gatekeeper_secure_log": gatekeeper_secure_log,
        "wordpress": wordpress,
        "mcp_worker": mcp_worker,
        "log_read_scopes": log_read_scopes,
        "log_read_files": log_read_files,
    }


def validate_runtime_capabilities(capabilities):
    """Validate persisted capability metadata before assembling a root script."""
    data = capabilities or {}
    if not isinstance(data, dict):
        raise ValueError("Runtime capabilities must be an object")
    unexpected = set(data) - _RUNTIME_CAPABILITY_FIELDS
    if unexpected:
        raise ValueError(
            "Unexpected runtime capability fields: "
            + ", ".join(sorted(unexpected))
        )
    services = []
    for value in data.get("watchdog_services", ()):
        unit = _systemd_unit(value)
        if unit not in services:
            services.append(unit)

    wordpress = data.get("wordpress")
    if wordpress:
        wordpress = {
            "plugin_dir": _managed_path(
                wordpress.get("plugin_dir"),
                "WordPress plugin directory",
                "/var/www",
            ),
            "quarantine_dir": _managed_path(
                wordpress.get("quarantine_dir"),
                "WordPress quarantine directory",
                "/opt/quarantine",
            ),
            "snapshot_root": _managed_path(
                wordpress.get("snapshot_root"),
                "WordPress snapshot root",
                "/opt/swarm",
            ),
        }

    log_read_scopes = []
    log_read_files = []
    for value in data.get("log_read_scopes", ()):
        kind, path = _log_read_target(value, "Log read scope")
        if kind != "scope":
            raise ValueError(f"Log read scope must be a service-log directory: {path}")
        if path not in log_read_scopes:
            log_read_scopes.append(path)
    for value in data.get("log_read_files", ()):
        kind, path = _log_read_target(value, "Log read file")
        if kind != "file":
            raise ValueError(f"Log read file must be an approved exact file: {path}")
        if path not in log_read_files:
            log_read_files.append(path)

    return {
        "watchdog_services": services,
        "gatekeeper_secure_log": bool(data.get("gatekeeper_secure_log", False)),
        "wordpress": wordpress,
        "mcp_worker": bool(data.get("mcp_worker", False)),
        "log_read_scopes": log_read_scopes,
        "log_read_files": log_read_files,
    }


def mcp_worker_linux_user(swarm_user):
    """Derive a separate per-universe account for untrusted MCP workers."""
    swarm_user = validate_linux_user(swarm_user, "Swarm Linux user")
    candidate = f"{swarm_user}-mcp"
    if len(candidate) > 31:
        digest = hashlib.sha256(swarm_user.encode("utf-8")).hexdigest()[:6]
        candidate = f"{swarm_user[:20].rstrip('-_')}-mcp-{digest}"
    return validate_linux_user(candidate, "MCP worker Linux user")


def _root_shell(script):
    """Run one fixed script as root, supporting root or passwordless-sudo SSH."""
    # This multiline script is assembled exclusively from validated or fixed
    # fragments above; shlex.quote is intentional because the public argument
    # helper correctly rejects control characters in operator-provided values.
    quoted = shlex.quote(script)
    return (
        "if [ \"$(id -u)\" -eq 0 ]; then "
        f"/bin/sh -c {quoted}; "
        "elif command -v sudo >/dev/null 2>&1; then "
        f"sudo -n /bin/sh -c {quoted}; "
        "else echo '[MATRIX][ERROR] Root or passwordless sudo is required.' >&2; exit 77; fi"
    )


def build_remote_matrixd_command(
    *,
    action,
    universe,
    linux_user,
    boot_flags=(),
    reboot_id=None,
    runtime_capabilities=None,
):
    """Build the shared Railgun/DeployDialog least-privilege command.

    Root is used only to provision service accounts and directory ownership.
    MatrixD and every native swarm agent run as ``linux_user``. Root grants are
    derived from the compiled directive and restricted to the exact resources
    required by Gatekeeper, service watchdogs, WordPress Plugin Guard, and the
    isolated MCP worker. The swarm account receives no general sudo permission.
    """
    if action not in {"start", "restart", "stop"}:
        raise ValueError("Remote action must be start, restart, or stop")

    universe = validate_remote_token(universe, "Universe name")
    linux_user = validate_linux_user(linux_user, "Swarm Linux user")
    capabilities = validate_runtime_capabilities(runtime_capabilities)
    capability_manifest = encode_runtime_capability_manifest(
        capabilities, universe=universe
    )
    flags = []
    for flag in boot_flags:
        if flag not in _ALLOWED_BOOT_FLAGS:
            raise ValueError(f"Unsupported MatrixD boot flag: {flag}")
        flags.append(flag)
    if reboot_id:
        reboot_id = validate_remote_token(reboot_id, "Reboot ID")
        flags.extend(("--reboot-id", reboot_id))

    restart_requested = action == "restart" or any(
        flag in flags for flag in ("--reboot", "--reboot-new", "--reboot-id")
    )

    q_universe = quote_remote_argument(universe, "Universe name")
    q_user = quote_remote_argument(linux_user, "Swarm Linux user")
    matrixd = "/matrix/.venv/bin/python3 /matrix/scripts/matrixd"
    common_env = (
        "env PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 SITE_ROOT=/matrix "
        "MATRIX_RUNTIME_CAPABILITIES_B64="
        f"{quote_remote_argument(capability_manifest, 'Capability manifest')}"
    )

    lines = [
        "set -eu",
        "cd /matrix",
        "command -v runuser >/dev/null 2>&1 || "
        "{ echo '[MATRIX][ERROR] runuser is required.' >&2; exit 69; }",
        f"SWARM_USER={q_user}",
        f"UNIVERSE={q_universe}",
    ]

    if action == "stop":
        lines.extend([
            # Root is the external control plane and can terminate a universe
            # that predates service-account isolation as well as a current one.
            f"{common_env} {matrixd} kill --universe {q_universe}",
        ])
        return _root_shell("\n".join(lines))

    q_flags = " ".join(
        quote_remote_argument(flag, "MatrixD boot argument") for flag in flags
    )

    lines.extend([
        *(
            [f"{common_env} {matrixd} kill --universe {q_universe}"]
            if restart_requested
            else []
        ),
        "if id -u \"$SWARM_USER\" >/dev/null 2>&1; then "
        "ACCOUNT_SHELL=$(getent passwd \"$SWARM_USER\" | cut -d: -f7); "
        "case \"$ACCOUNT_SHELL\" in /usr/sbin/nologin|/sbin/nologin|/bin/false) ;; "
        "*) echo '[MATRIX][ERROR] Refusing an existing login-capable account.' >&2; exit 78 ;; esac; "
        "else useradd --system --no-create-home --home-dir /nonexistent "
        "--shell /usr/sbin/nologin \"$SWARM_USER\"; fi",
        "SWARM_GROUP=$(id -gn \"$SWARM_USER\")",
        "install -d -o \"$SWARM_USER\" -g \"$SWARM_GROUP\" -m 0700 "
        "\"/matrix/universes/runtime/$UNIVERSE\" "
        "\"/matrix/universes/static/$UNIVERSE\"",
        "chown -hR \"$SWARM_USER:$SWARM_GROUP\" "
        "\"/matrix/universes/runtime/$UNIVERSE\" "
        "\"/matrix/universes/static/$UNIVERSE\"",
    ])

    requested_log_scopes = capabilities["log_read_scopes"]
    requested_log_files = capabilities["log_read_files"]
    log_access_requested = bool(requested_log_scopes or requested_log_files)
    lines.extend([
        # Reconcile every Railgun-managed log ACL before applying the current
        # directive. This prevents a removed agent from leaving access behind.
        "if command -v setfacl >/dev/null 2>&1; then",
    ])
    for path in _ALLOWED_LOG_SCOPE_ROOTS:
        q_path = quote_remote_argument(path, "Managed log scope")
        lines.extend([
            f"  if [ -d {q_path} ]; then",
            f"    find {q_path} -type f -exec setfacl -x \"u:$SWARM_USER\" {{}} + 2>/dev/null || true",
            f"    find {q_path} -type d -exec setfacl -x \"u:$SWARM_USER\" {{}} + 2>/dev/null || true",
            f"    find {q_path} -type d -exec setfacl -d -x \"u:$SWARM_USER\" {{}} + 2>/dev/null || true",
            "  fi",
        ])
    for path in sorted(_ALLOWED_EXACT_LOG_FILES):
        q_path = quote_remote_argument(path, "Managed log file")
        lines.append(
            f"  if [ -f {q_path} ]; then setfacl -x \"u:$SWARM_USER\" {q_path} 2>/dev/null || true; fi"
        )
    lines.extend([
        "else",
        *(
            ["  echo '[LOG-ACCESS][ERROR] setfacl/acl is required.' >&2; exit 69"]
            if log_access_requested
            else ["  :"]
        ),
        "fi",
    ])

    if log_access_requested:
        lines.append("command -v readlink >/dev/null 2>&1 || { echo '[LOG-ACCESS][ERROR] readlink is required.' >&2; exit 69; }")
    for path in requested_log_scopes:
        q_path = quote_remote_argument(path, "Log read scope")
        lines.extend([
            f"if [ -d {q_path} ]; then",
            f"  REAL_LOG_SCOPE=$(readlink -f -- {q_path})",
            f"  [ \"$REAL_LOG_SCOPE\" = {q_path} ] || {{ echo '[LOG-ACCESS][ERROR] Refusing redirected log scope: {path}' >&2; exit 66; }}",
            f"  find {q_path} -type d -exec setfacl -m \"u:$SWARM_USER:r-x\" {{}} +",
            f"  find {q_path} -type d -exec setfacl -d -m \"u:$SWARM_USER:r-x\" {{}} +",
            f"  find {q_path} -type f -exec setfacl -m \"u:$SWARM_USER:r--\" {{}} +",
            f"  echo '[LOG-ACCESS] READ {path}/**'",
            "else",
            f"  echo '[LOG-ACCESS][WARN] Requested log scope is absent: {path}' >&2",
            "fi",
        ])
    for path in requested_log_files:
        q_path = quote_remote_argument(path, "Log read file")
        lines.extend([
            f"if [ -f {q_path} ]; then",
            f"  REAL_LOG_FILE=$(readlink -f -- {q_path})",
            f"  [ \"$REAL_LOG_FILE\" = {q_path} ] || {{ echo '[LOG-ACCESS][ERROR] Refusing redirected log file: {path}' >&2; exit 66; }}",
            f"  setfacl -m \"u:$SWARM_USER:r--\" {q_path}",
            f"  echo '[LOG-ACCESS] READ {path}'",
            "else",
            f"  echo '[LOG-ACCESS][WARN] Requested log file is absent: {path}' >&2",
            "fi",
        ])

    watchdog_services = capabilities["watchdog_services"]
    if watchdog_services:
        sudo_commands = ", ".join(
            f"/usr/bin/systemctl restart {unit}"
            for unit in watchdog_services
        )
        q_sudo_commands = quote_remote_argument(
            sudo_commands, "Watchdog sudo commands"
        )
        lines.extend([
            "command -v sudo >/dev/null 2>&1 || "
            "{ echo '[WATCHDOG][ERROR] sudo is required.' >&2; exit 69; }",
            "command -v visudo >/dev/null 2>&1 || "
            "{ echo '[WATCHDOG][ERROR] visudo is required.' >&2; exit 69; }",
            "SUDOERS_TMP=$(mktemp /etc/sudoers.d/.matrixswarm-watchdogs.XXXXXX)",
            f"printf '%s ALL=(root) NOPASSWD: %s\\n' \"$SWARM_USER\" {q_sudo_commands} > \"$SUDOERS_TMP\"",
            "chown root:root \"$SUDOERS_TMP\" && chmod 0440 \"$SUDOERS_TMP\"",
            "visudo -cf \"$SUDOERS_TMP\" >/dev/null",
            "mv -f \"$SUDOERS_TMP\" \"/etc/sudoers.d/matrixswarm-$SWARM_USER-watchdogs\"",
        ])
    else:
        lines.append('rm -f "/etc/sudoers.d/matrixswarm-$SWARM_USER-watchdogs"')

    # Matrix normally runs as the isolated universe account, so it cannot
    # unlink legacy boot directives from the root-owned boot_directives
    # directory.  Grant only the two exact cleanup forms exposed by the
    # confirmed teardown dialog.  The validated universe is embedded in the
    # sudoers command; no wildcard, shell, arbitrary matrixd action, or other
    # universe is authorized.
    teardown_commands = ", ".join((
        f"/matrix/.venv/bin/python3 /matrix/scripts/matrixd kill "
        f"--universe {universe} --delete-directive-with-key",
        f"/matrix/.venv/bin/python3 /matrix/scripts/matrixd kill "
        f"--universe {universe} --delete-directive-with-key --clean-up",
    ))
    q_teardown_commands = quote_remote_argument(
        teardown_commands, "Universe teardown sudo commands"
    )
    lines.extend([
        "command -v sudo >/dev/null 2>&1 || "
        "{ echo '[TEARDOWN][ERROR] sudo is required.' >&2; exit 69; }",
        "command -v visudo >/dev/null 2>&1 || "
        "{ echo '[TEARDOWN][ERROR] visudo is required.' >&2; exit 69; }",
        "SUDOERS_TMP=$(mktemp /etc/sudoers.d/.matrixswarm-teardown.XXXXXX)",
        f"printf '%s ALL=(root) NOPASSWD: %s\\n' \"$SWARM_USER\" "
        f"{q_teardown_commands} > \"$SUDOERS_TMP\"",
        "chown root:root \"$SUDOERS_TMP\" && chmod 0440 \"$SUDOERS_TMP\"",
        "visudo -cf \"$SUDOERS_TMP\" >/dev/null",
        "mv -f \"$SUDOERS_TMP\" "
        "\"/etc/sudoers.d/matrixswarm-$SWARM_USER-teardown\"",
    ])

    if capabilities["gatekeeper_secure_log"]:
        lines.extend([
            "getent group matrix-secure-readers >/dev/null 2>&1 || groupadd --system matrix-secure-readers",
            "usermod -aG matrix-secure-readers \"$SWARM_USER\"",
            "if [ -e /var/log/secure ]; then",
            "  chgrp matrix-secure-readers /var/log/secure",
            "  chmod 0640 /var/log/secure",
            "  AUTH_RULE_FILE=",
            "  for CANDIDATE in /etc/rsyslog.conf /etc/rsyslog.d/*.conf; do",
            "    [ -f \"$CANDIDATE\" ] || continue",
            "    if grep -q 'var/log/secure' \"$CANDIDATE\"; then AUTH_RULE_FILE=$CANDIDATE; break; fi",
            "  done",
            "  [ -n \"$AUTH_RULE_FILE\" ] || { echo '[GATEKEEPER][ERROR] rsyslog /var/log/secure rule not found.' >&2; exit 66; }",
            "  if ! grep 'var/log/secure' \"$AUTH_RULE_FILE\" | grep -q 'fileGroup=\"matrix-secure-readers\"'; then",
            "    [ -f \"$AUTH_RULE_FILE.matrixswarm.bak\" ] || cp -a \"$AUTH_RULE_FILE\" \"$AUTH_RULE_FILE.matrixswarm.bak\"",
            "    sed -i -E 's#^authpriv\\.\\*.*var/log/secure.*$#authpriv.* action(type=\"omfile\" file=\"/var/log/secure\" fileOwner=\"root\" fileGroup=\"matrix-secure-readers\" fileCreateMode=\"0640\")#' \"$AUTH_RULE_FILE\"",
            "    rsyslogd -N1 >/dev/null",
            "    /usr/bin/systemctl restart rsyslog.service",
            "  fi",
            "elif [ -e /var/log/auth.log ]; then",
            "  echo '[GATEKEEPER][WARN] /var/log/auth.log requires distro-specific persistent ACL provisioning.' >&2",
            "fi",
        ])
    else:
        lines.extend([
            "if getent group matrix-secure-readers >/dev/null 2>&1; then",
            "  gpasswd -d \"$SWARM_USER\" matrix-secure-readers >/dev/null 2>&1 || true",
            "fi",
        ])

    wordpress = capabilities["wordpress"]
    if wordpress:
        q_plugin_dir = quote_remote_argument(
            wordpress["plugin_dir"], "WordPress plugin directory"
        )
        q_quarantine_dir = quote_remote_argument(
            wordpress["quarantine_dir"], "WordPress quarantine directory"
        )
        q_snapshot_root = quote_remote_argument(
            wordpress["snapshot_root"], "WordPress snapshot root"
        )
        lines.append(
            "install -d -o root -g root -m 0700 /etc/matrixswarm/capabilities"
        )

    lines.extend([
            # Revoke every path recorded by the previous Railgun deployment
            # before applying this directive. The root-owned manifest contains
            # paths only (never keys or directive data).
            "WP_ACL_MANIFEST=\"/etc/matrixswarm/capabilities/$SWARM_USER.wordpress-acl\"",
            "if [ -f \"$WP_ACL_MANIFEST\" ]; then",
            "  command -v setfacl >/dev/null 2>&1 || { echo '[PLUGIN-GUARD][ERROR] setfacl/acl is required to revoke the prior policy.' >&2; exit 69; }",
            "  command -v readlink >/dev/null 2>&1 || { echo '[PLUGIN-GUARD][ERROR] readlink is required to revoke the prior policy.' >&2; exit 69; }",
            "  while IFS= read -r OLD_PATH; do",
            "    [ -n \"$OLD_PATH\" ] || continue",
            "    case \"$OLD_PATH\" in /var/www/*|/opt/quarantine/*|/opt/swarm/*) ;; *) continue ;; esac",
            "    [ -e \"$OLD_PATH\" ] || continue",
            "    OLD_REAL=$(readlink -f -- \"$OLD_PATH\")",
            "    [ \"$OLD_REAL\" = \"$OLD_PATH\" ] || { echo '[PLUGIN-GUARD][ERROR] Refusing redirected prior ACL path.' >&2; exit 66; }",
            "    if [ -d \"$OLD_PATH\" ]; then",
            "      find \"$OLD_PATH\" -type f -exec setfacl -x \"u:$SWARM_USER\" {} + 2>/dev/null || true",
            "      find \"$OLD_PATH\" -type d -exec setfacl -x \"u:$SWARM_USER\" {} + 2>/dev/null || true",
            "      find \"$OLD_PATH\" -type d -exec setfacl -d -x \"u:$SWARM_USER\" {} + 2>/dev/null || true",
            "    else",
            "      setfacl -x \"u:$SWARM_USER\" \"$OLD_PATH\" 2>/dev/null || true",
            "    fi",
            "  done < \"$WP_ACL_MANIFEST\"",
            "  rm -f \"$WP_ACL_MANIFEST\"",
            "fi",
    ])

    if wordpress:
        lines.extend([
            "command -v setfacl >/dev/null 2>&1 || { echo '[PLUGIN-GUARD][ERROR] setfacl/acl package is required.' >&2; exit 69; }",
            "command -v readlink >/dev/null 2>&1 || { echo '[PLUGIN-GUARD][ERROR] readlink is required.' >&2; exit 69; }",
            f"PLUGIN_DIR={q_plugin_dir}",
            f"QUARANTINE_DIR={q_quarantine_dir}",
            f"SNAPSHOT_ROOT={q_snapshot_root}",
            "[ -d \"$PLUGIN_DIR\" ] || { printf '[PLUGIN-GUARD][ERROR] Plugin directory not found: %s\\n' \"$PLUGIN_DIR\" >&2; exit 66; }",
            "install -d -o root -g root -m 0750 \"$QUARANTINE_DIR\"",
            "install -d -o root -g root -m 0750 \"$SNAPSHOT_ROOT\"",
            "for MANAGED_DIR in \"$PLUGIN_DIR\" \"$QUARANTINE_DIR\" \"$SNAPSHOT_ROOT\"; do",
            "  REAL_MANAGED_DIR=$(readlink -f -- \"$MANAGED_DIR\")",
            "  [ \"$REAL_MANAGED_DIR\" = \"$MANAGED_DIR\" ] || { echo '[PLUGIN-GUARD][ERROR] Refusing redirected managed directory.' >&2; exit 66; }",
            "  find \"$MANAGED_DIR\" -type d -exec setfacl -m \"u:$SWARM_USER:rwx,d:u:$SWARM_USER:rwx\" {} +",
            "  find \"$MANAGED_DIR\" -type f -exec setfacl -m \"u:$SWARM_USER:rw-\" {} +",
            "done",
            "WP_ACL_TMP=$(mktemp /etc/matrixswarm/capabilities/.wordpress-acl.XXXXXX)",
            "printf '%s\\n%s\\n%s\\n' \"$PLUGIN_DIR\" \"$QUARANTINE_DIR\" \"$SNAPSHOT_ROOT\" > \"$WP_ACL_TMP\"",
            "chown root:root \"$WP_ACL_TMP\" && chmod 0600 \"$WP_ACL_TMP\"",
            "mv -f \"$WP_ACL_TMP\" \"$WP_ACL_MANIFEST\"",
        ])

    if capabilities["mcp_worker"]:
        worker_user = mcp_worker_linux_user(linux_user)
        q_worker_user = quote_remote_argument(worker_user, "MCP worker Linux user")
        lines.extend([
            "command -v sudo >/dev/null 2>&1 || "
            "{ echo '[MCP][ERROR] sudo is required for the sealed worker launcher.' >&2; exit 69; }",
            "command -v visudo >/dev/null 2>&1 || "
            "{ echo '[MCP][ERROR] visudo is required for the sealed worker launcher.' >&2; exit 69; }",
            "test -x /usr/local/libexec/matrix-mcp-launch",
            "test -x /matrix/mcp/.venv/bin/python3",
            "test -f /matrix/agents/python_core/mcp_reflex/worker/mcp_stdio_worker.py",
            f"MCP_USER={q_worker_user}",
            "if id -u \"$MCP_USER\" >/dev/null 2>&1; then "
            "ACCOUNT_SHELL=$(getent passwd \"$MCP_USER\" | cut -d: -f7); "
            "case \"$ACCOUNT_SHELL\" in /usr/sbin/nologin|/sbin/nologin|/bin/false) ;; "
            "*) echo '[MCP][ERROR] Refusing an existing login-capable account.' >&2; exit 78 ;; esac; "
            "else useradd --system --no-create-home --home-dir /nonexistent "
            "--shell /usr/sbin/nologin \"$MCP_USER\"; fi",
            "MCP_GROUP=$(id -gn \"$MCP_USER\")",
            "MCP_WORK_DIR=\"/matrix/mcp/workers/$UNIVERSE\"",
            "install -d -o \"$MCP_USER\" -g \"$MCP_GROUP\" -m 0700 \"$MCP_WORK_DIR\"",
            "install -d -o root -g root -m 0700 /etc/matrixswarm/mcp-launchers",
            "WORKER_SCRIPT=/matrix/agents/python_core/mcp_reflex/worker/mcp_stdio_worker.py",
            "WORKER_HASH=$(sha256sum \"$WORKER_SCRIPT\" | awk '{print $1}')",
            "PROFILE_TMP=$(mktemp /etc/matrixswarm/mcp-launchers/.profile.XXXXXX)",
            "printf '{\"worker_user\":\"%s\",\"working_directory\":\"%s\","
            "\"python\":\"/matrix/mcp/.venv/bin/python3\","
            "\"worker_script\":\"%s\",\"worker_sha256\":\"%s\"}\\n' "
            "\"$MCP_USER\" \"$MCP_WORK_DIR\" \"$WORKER_SCRIPT\" \"$WORKER_HASH\" "
            "> \"$PROFILE_TMP\"",
            "chown root:root \"$PROFILE_TMP\" && chmod 0600 \"$PROFILE_TMP\"",
            "mv -f \"$PROFILE_TMP\" \"/etc/matrixswarm/mcp-launchers/$SWARM_USER.json\"",
            "SUDOERS_TMP=$(mktemp /etc/sudoers.d/.matrixswarm-mcp.XXXXXX)",
            "printf '%s ALL=(root) NOPASSWD: /usr/local/libexec/matrix-mcp-launch\\n' "
            "\"$SWARM_USER\" > \"$SUDOERS_TMP\"",
            "chown root:root \"$SUDOERS_TMP\" && chmod 0440 \"$SUDOERS_TMP\"",
            "visudo -cf \"$SUDOERS_TMP\" >/dev/null",
            "mv -f \"$SUDOERS_TMP\" \"/etc/sudoers.d/matrixswarm-$SWARM_USER-mcp\"",
        ])
    else:
        # A later directive that removes MCP must also revoke the exact grant
        # and root-owned profile created by an earlier MCP-enabled deployment.
        lines.extend([
            "rm -f \"/etc/sudoers.d/matrixswarm-$SWARM_USER-mcp\"",
            "rm -f \"/etc/matrixswarm/mcp-launchers/$SWARM_USER.json\"",
        ])

    boot_command = (
        f"runuser -u \"$SWARM_USER\" -- {common_env} "
        f"{matrixd} boot --universe {q_universe} --directive-stdin"
    )
    if q_flags:
        boot_command += f" {q_flags}"

    lines.append(boot_command)
    return _root_shell("\n".join(lines))
