"""Fail-closed builders for MatrixOS SSH launch commands."""

import hashlib
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
}
_WATCHDOG_SERVICE_BY_AGENT = {
    "apache_watchdog": "httpd",
    "redis_watchdog": "redis",
    "mysql_watchdog": "mysqld",
}
_ALLOWED_WATCHDOG_UNITS = {
    "apache2.service",
    "httpd.service",
    "mariadb.service",
    "mysqld.service",
    "redis.service",
}


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
    if not cleaned or any(ch in cleaned for ch in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} is required and must not contain controls")
    normalized = posixpath.normpath(cleaned)
    root = posixpath.normpath(allowed_root)
    if not normalized.startswith(root.rstrip("/") + "/"):
        raise ValueError(f"{label} must be beneath {root}")
    return normalized


def derive_runtime_capabilities(agent_tree):
    """Derive the least privileges required by enabled agents in a directive."""
    services = []
    gatekeeper_secure_log = False
    wordpress = None
    mcp_worker = False

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
        elif name == "gatekeeper":
            gatekeeper_secure_log = True
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
                "trusted_plugins_path": _managed_path(
                    config.get(
                        "trusted_plugins_path",
                        "/opt/swarm/guard/trusted_plugins.json",
                    ),
                    "WordPress trust database",
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
    }


def validate_runtime_capabilities(capabilities):
    """Validate persisted capability metadata before assembling a root script."""
    data = capabilities or {}
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
            "trusted_plugins_path": _managed_path(
                wordpress.get("trusted_plugins_path"),
                "WordPress trust database",
                "/opt/swarm",
            ),
        }

    return {
        "watchdog_services": services,
        "gatekeeper_secure_log": bool(data.get("gatekeeper_secure_log", False)),
        "wordpress": wordpress,
        "mcp_worker": bool(data.get("mcp_worker", False)),
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
    directive_path=None,
    swarm_key=None,
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
    flags = []
    for flag in boot_flags:
        if flag not in _ALLOWED_BOOT_FLAGS:
            raise ValueError(f"Unsupported MatrixD boot flag: {flag}")
        flags.append(flag)
    if reboot_id:
        reboot_id = validate_remote_token(reboot_id, "Reboot ID")
        flags.extend(("--reboot-id", reboot_id))

    q_universe = quote_remote_argument(universe, "Universe name")
    q_user = quote_remote_argument(linux_user, "Swarm Linux user")
    matrixd = "/matrix/.venv/bin/python3 /matrix/scripts/matrixd"
    common_env = (
        "env PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 SITE_ROOT=/matrix"
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

    if not directive_path:
        raise ValueError("Directive path is required for start or restart")
    if not swarm_key:
        raise ValueError("SWARM_KEY is required for start or restart")

    q_directive = quote_remote_argument(directive_path, "Directive path")
    q_swarm_key = quote_remote_argument(swarm_key, "SWARM_KEY")
    q_flags = " ".join(
        quote_remote_argument(flag, "MatrixD boot argument") for flag in flags
    )

    lines.extend([
        *(
            [f"{common_env} {matrixd} kill --universe {q_universe}"]
            if action == "restart" or "--reboot" in flags
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
        f"test -f {q_directive}",
        f"chown \"$SWARM_USER:$SWARM_GROUP\" {q_directive}",
        f"chmod 0600 {q_directive}",
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

    wordpress = capabilities["wordpress"]
    if wordpress:
        q_plugin_dir = quote_remote_argument(
            wordpress["plugin_dir"], "WordPress plugin directory"
        )
        q_quarantine_dir = quote_remote_argument(
            wordpress["quarantine_dir"], "WordPress quarantine directory"
        )
        q_trust_path = quote_remote_argument(
            wordpress["trusted_plugins_path"], "WordPress trust database"
        )
        lines.extend([
            "command -v setfacl >/dev/null 2>&1 || { echo '[PLUGIN-GUARD][ERROR] setfacl/acl package is required.' >&2; exit 69; }",
            f"PLUGIN_DIR={q_plugin_dir}",
            f"QUARANTINE_DIR={q_quarantine_dir}",
            f"TRUST_PATH={q_trust_path}",
            "[ -d \"$PLUGIN_DIR\" ] || { printf '[PLUGIN-GUARD][ERROR] Plugin directory not found: %s\\n' \"$PLUGIN_DIR\" >&2; exit 66; }",
            "install -d -o root -g root -m 0750 \"$QUARANTINE_DIR\"",
            "install -d -o root -g root -m 0750 \"$(dirname \"$TRUST_PATH\")\"",
            "touch \"$TRUST_PATH\"",
            "for MANAGED_DIR in \"$PLUGIN_DIR\" \"$QUARANTINE_DIR\"; do",
            "  find \"$MANAGED_DIR\" -type d -exec setfacl -m \"u:$SWARM_USER:rwx,d:u:$SWARM_USER:rwx\" {} +",
            "  find \"$MANAGED_DIR\" -type f -exec setfacl -m \"u:$SWARM_USER:rw-\" {} +",
            "done",
            "setfacl -m \"u:$SWARM_USER:rwx\" \"$(dirname \"$TRUST_PATH\")\"",
            "setfacl -m \"u:$SWARM_USER:rw-\" \"$TRUST_PATH\"",
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
            "printf '{\"worker_user\":\"%s\",\"working_directory\":\"%s\",' "
            "'\"python\":\"/matrix/mcp/.venv/bin/python3\",' "
            "'\"worker_script\":\"%s\",\"worker_sha256\":\"%s\"}\\n' "
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
        f"runuser -u \"$SWARM_USER\" -- {common_env} SWARM_KEY={q_swarm_key} "
        f"{matrixd} boot --universe {q_universe} --directive {q_directive}"
    )
    if q_flags:
        boot_command += f" {q_flags}"

    lines.append(boot_command)
    return _root_shell("\n".join(lines))


def redact_remote_secret(command, secret):
    """Redact a quoted secret from a command displayed in Phoenix."""
    if not secret:
        return command
    return command.replace(
        quote_remote_argument(secret, "secret"),
        "'[REDACTED]'",
    )
