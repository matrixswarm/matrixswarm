# Log Watcher

`log_watcher` collects recent log excerpts into a digest on request. It can also
send scheduled digests to Oracle when `enable_oracle` is enabled. For continuous
single-file monitoring, use `log_health`.

## Edit log locations in Phoenix

1. Open the deployment workspace and double-click `log_watcher`.
2. Edit each collector's server log files, one absolute Linux file path per line.
   Add or remove collectors as needed. Names are labels; custom collectors use
   the same shared reader and do not require a Python collector module.
3. Set the maximum lines per file, number of rotated files, and rotation style.
4. Save the editor and workspace, resolve any pending constraints, and redeploy.
5. Reconnect and open the LogWatcher panel. Its checkboxes use the deployment's
   configured collectors; hover over a checkbox to see its paths. Select the
   collectors and choose Generate Digest.

New metadata uses Ubuntu-style paths, including `/var/log/apache2/error.log`,
`/var/log/auth.log`, and `/var/log/syslog`. These are examples, not discovery:
remove collectors for services you do not run and set the actual paths on your
server. Existing workspaces retain their saved locations and settings.
For other distributions, paths such as `/var/log/httpd/error_log`,
`/var/log/secure`, and `/var/log/messages` may be appropriate.

## Collector configuration

```json
{
  "collectors": {
    "httpd": {
      "paths": ["/var/log/apache2/error.log"],
      "max_lines": 50,
      "rotate_depth": 1,
      "rotation_style": "numbered"
    }
  }
}
```

- `paths`: 1–16 absolute file paths per collector. Directories and wildcard
  patterns are not supported. File access uses the agent's existing Linux rights.
- `max_lines`: 1–5000 recent lines from each file, default 500 when omitted.
  Each tail reads at most the last 1 MiB and reports when that cap limits output.
- `rotate_depth`: 0–30 older files in addition to the current file. Default 1.
- `rotation_style`: `numbered` reads `.1`, `.2`, etc.; `dated` reads suffixes
  such as `-20261004` for previous days in the server's local timezone.
  Existing configurations without this field retain dated rotation.
- Compressed logs are not supported. Missing older rotations are skipped;
  missing base files and read failures appear as errors in the digest.

The workspace editor supports up to 32 collectors and preserves unrelated
settings, routes, and collector fields. Removing every collector disables log
collection. The panel requires at least one selected collector before sending.

## Other settings

The editor also exposes existing scalar settings: `check_interval_sec`,
`patrol_interval_hours`, `enable_oracle`, `oracle_role`, `oracle_timeout`, and
`alert_role`. Scheduled Oracle patrols run only when `enable_oracle` is enabled;
manual Oracle Analysis is selected separately in the digest panel. Log content
submitted to Oracle can be sent to its configured external model provider.

The editor validates paths against Railgun's deployment allowlist. Approved
service directories include Apache, Nginx, MySQL/MariaDB and Redis log directories.
Approved exact files include `/var/log/auth.log`, `/var/log/secure`,
`/var/log/syslog`, `/var/log/messages`, `/var/log/mail.log`, `/var/log/maillog`,
`/var/log/dovecot.log`, `/var/log/fail2ban.log`, and `/var/log/mysqld.log`.

Saving alone changes no permissions. Deployment provisions read access using
Railgun's existing policy: directory scopes for approved service directories,
exact-file access for standalone logs. Exact-file grants do not automatically
cover rotated siblings or replacement files; those still require appropriate
server-side access. Missing files are reported during provisioning.

These grants currently apply to the swarm Linux account. This feature does not
change agent identities or the pending per-agent isolation work. The log reader
does not execute shell commands.
