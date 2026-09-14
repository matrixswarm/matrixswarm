# Authored by Daniel F MacDonald and ChatGPT 5.1 aka The Generals
import os
import shlex
import json
import time
import gzip
import hashlib
import base64
import re
import subprocess
from pathlib import Path

from rsync_boy.factory.ssh_transport import SSHTransport, parse_ssh_profile


_SAFE_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

class MySQLDumpJob:
    """
    Fire-and-forget MySQL dump job.
    Contract:
      ctx = shared["context"] = { "job_id": str, "credentials": dict, "config": dict }
    """
    def __init__(self, log, shared):
        self.log = log
        self.shared = shared
        self.ctx = shared.get("context", {}) or {}
        self.job_id = self.ctx.get("job_id") or "mysql_dump"

    # ---------------------------------------------------------
    def run(self):
        started = time.time()
        try:
            cfg = self.ctx.get("config", {}) or {}

            profile = parse_ssh_profile(cfg)
            job = self._validate_and_normalize_cfg(cfg)

            self.log(f"[MYSQLDUMP][{self.job_id}] Starting dump for db='{job['database']}'")

            with SSHTransport(profile) as transport:
                if job["mysql_via_ssh"]:
                    self._probe_mysql_connection(job, transport)
                else:
                    self._require_binary("mysql")
                    self._require_binary("mysqldump")
                    self._probe_mysql_connection(job)

                # Dump -> optional gzip -> sha256 -> manifest
                local_file = self._dump_database(
                    job, transport if job["mysql_via_ssh"] else None
                )
                if job["compress"]:
                    local_file = self._gzip_file(local_file)

                sha = self._sha256_file(local_file)
                manifest_path = self._write_manifest(job, local_file, sha, started)

                # Remote ensure + upload both dump + manifest
                self._remote_mkdir(transport, job["remote_path"])
                self._rsync_upload(transport, local_file, job["remote_path"])
                self._rsync_upload(transport, manifest_path, job["remote_path"])

                # Optional prune
                prune = job.get("remote_prune", {})
                if prune and int(prune.get("keep_days", 0)) > 0:
                    self._remote_prune(transport, job["remote_path"], prune)
                self._local_prune(job)

            self.shared["result"] = "ok"
            self.shared["finished_at"] = time.time()
            self.log(f"[MYSQLDUMP][{self.job_id}] ✅ Completed in {int(time.time() - started)}s")

        except Exception as e:
            self.shared["result"] = "error"
            self.shared["error"] = str(e)
            self.shared["finished_at"] = time.time()
            self.log(f"[MYSQLDUMP][{self.job_id}][ERROR] {e}", level="ERROR")
            raise

    # ---------------------------------------------------------
    # Parsing / Validation
    # ---------------------------------------------------------
    def _validate_and_normalize_cfg(self, cfg: dict) -> dict:
        mysql = cfg.get("mysql", {}) or {}

        # Accept both naming styles
        db = mysql.get("database", "").strip()
        host = mysql.get("mysql_host") or mysql.get("host") or "localhost"
        port = int(mysql.get("mysql_port") or mysql.get("port") or 3306)
        user = mysql.get("mysql_user") or mysql.get("username") or ""
        pwd = mysql.get("mysql_password") or mysql.get("password") or ""
        socket_path = mysql.get("mysql_socket") or mysql.get("socket") or ""

        requested_auth = str(
            mysql.get("auth_type")
            or mysql.get("authentication")
            or mysql.get("auth_mode")
            or ""
        ).strip().lower().replace("-", "_")
        socket_modes = {"socket", "local_socket", "unix_socket"}
        password_modes = {"password", "tcp", "tcp_password"}

        if requested_auth in socket_modes:
            auth_type = "local_socket"
        elif requested_auth in password_modes:
            auth_type = "password"
        elif requested_auth:
            raise ValueError(
                "config.mysql.auth_type must be 'local_socket' or 'password'"
            )
        else:
            local_hosts = {"", "localhost", "127.0.0.1", "::1"}
            auth_type = (
                "local_socket"
                if not pwd and str(host).strip().lower() in local_hosts
                else "password"
            )

        if not db:
            raise ValueError("config.mysql.database is required")

        remote_path = (cfg.get("remote_path") or "").strip()
        if not remote_path.startswith("/") or remote_path == "/":
            raise ValueError("config.remote_path must be an absolute non-root path")

        local_tmp = (cfg.get("local_tmp") or "/tmp/mysql_dumps").strip()
        filename_prefix = (cfg.get("filename_prefix") or db).strip()
        keep_days = int((cfg.get("remote_prune") or {}).get("keep_days", 14))

        if not os.path.isabs(local_tmp) or os.path.abspath(local_tmp) == os.path.abspath(os.sep):
            raise ValueError("config.local_tmp must be an absolute non-root path")
        local_tmp = os.path.abspath(local_tmp)
        if os.path.lexists(local_tmp) and os.path.islink(local_tmp):
            raise ValueError("config.local_tmp must not be a symbolic link")
        if not _SAFE_PREFIX.fullmatch(filename_prefix):
            raise ValueError("config.filename_prefix contains unsafe characters")
        if not 0 <= keep_days <= 3650:
            raise ValueError("config.remote_prune.keep_days must be between 0 and 3650")

        job = {
            "mysql_host": host,
            "mysql_port": port,
            "mysql_user": user,
            "mysql_password": pwd,
            "mysql_socket": str(socket_path).strip(),
            "mysql_auth_type": auth_type,
            "mysql_via_ssh": bool(cfg.get("mysql_via_ssh", True)),
            "database": db,

            # job options living at config.*
            "dump_flags": (cfg.get("dump_flags") or "").strip(),
            "local_tmp": local_tmp,
            "remote_path": remote_path,
            "compress": bool(cfg.get("compress", True)),
            "filename_prefix": filename_prefix,
            "remote_prune": {"keep_days": keep_days},
        }

        if job["mysql_auth_type"] == "password":
            if not job["mysql_user"]:
                raise ValueError("config.mysql.mysql_user is required")
            if not job["mysql_password"]:
                raise ValueError("config.mysql.mysql_password is required")

        if not (1 <= job["mysql_port"] <= 65535):
            raise ValueError("config.mysql.mysql_port out of range")

        os.makedirs(job["local_tmp"], mode=0o700, exist_ok=True)
        if hasattr(os, "geteuid") and os.stat(job["local_tmp"]).st_uid != os.geteuid():
            raise ValueError("config.local_tmp must be owned by the MatrixOS user")
        os.chmod(job["local_tmp"], 0o700)
        return job

    # ---------------------------------------------------------
    # Preflight helpers
    # ---------------------------------------------------------
    def _require_binary(self, name: str):
        if subprocess.call(["which", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            raise RuntimeError(f"Required binary not found: {name}")

    def _mysql_connection(self, job: dict) -> tuple[list[str], dict]:
        """Build local MySQL client arguments without exposing the password."""
        env = os.environ.copy()
        args = []

        if job["mysql_auth_type"] == "local_socket":
            args.append("--protocol=socket")
            if job["mysql_socket"]:
                args += ["--socket", job["mysql_socket"]]
            if job["mysql_user"]:
                args += ["-u", job["mysql_user"]]
        else:
            env["MYSQL_PWD"] = str(job["mysql_password"])
            args += [
                "--protocol=TCP",
                "-h", job["mysql_host"],
                "-P", str(job["mysql_port"]),
                "-u", job["mysql_user"],
            ]

        return args, env

    @staticmethod
    def _mysql_option_value(value) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _process_error(value) -> str:
        if isinstance(value, bytes):
            text = value.decode("utf-8", "ignore")
        else:
            text = str(value or "")
        text = text.strip()
        if len(text) <= 4000:
            return text
        return f"{text[:1800]}\n... output shortened ...\n{text[-1800:]}"

    def _remote_mysql_script(self, job: dict, binary: str, args: list[str]) -> bytes:
        """Build a stdin-only script that uses a short-lived remote option file."""
        lines = ["[client]"]
        if job["mysql_user"]:
            lines.append(f'user="{self._mysql_option_value(job["mysql_user"])}"')
        if job["mysql_password"]:
            lines.append(f'password="{self._mysql_option_value(job["mysql_password"])}"')

        if job["mysql_auth_type"] == "local_socket":
            lines.append("protocol=SOCKET")
            if job["mysql_socket"]:
                lines.append(f'socket="{self._mysql_option_value(job["mysql_socket"])}"')
        else:
            lines.extend([
                "protocol=TCP",
                f'host="{self._mysql_option_value(job["mysql_host"])}"',
                f"port={job['mysql_port']}",
            ])

        encoded_defaults = base64.b64encode(
            ("\n".join(lines) + "\n").encode("utf-8")
        ).decode("ascii")
        alternatives = {
            "mysql": ("mariadb", "mysql"),
            "mysqldump": ("mariadb-dump", "mysqldump"),
        }.get(binary, (binary,))
        command = " ".join([
            '"$client_binary"',
            '--defaults-extra-file="$defaults_file"',
            *(shlex.quote(str(arg)) for arg in args),
        ])
        return f"""set -eu
defaults_file=$(mktemp)
trap 'rm -f "$defaults_file"' EXIT HUP INT TERM
chmod 600 "$defaults_file"
printf '%s' {shlex.quote(encoded_defaults)} | base64 --decode > "$defaults_file"
client_binary=
for candidate in {' '.join(shlex.quote(name) for name in alternatives)}; do
  if command -v "$candidate" >/dev/null 2>&1; then
    client_binary="$candidate"
    break
  fi
done
if [ -z "$client_binary" ]; then
  printf 'Required database client not found: %s\n' {shlex.quote(' or '.join(alternatives))} >&2
  exit 127
fi
{command}
""".encode("utf-8")

    def _run_mysql_over_ssh(
        self,
        transport: SSHTransport,
        job: dict,
        binary: str,
        args: list[str],
        *,
        stdout=subprocess.PIPE,
    ):
        return transport.run_script(
            self._remote_mysql_script(job, binary, args),
            check=False,
            stdout=stdout,
        )

    def _probe_mysql_connection(
        self, job: dict, transport: SSHTransport | None = None
    ):
        """Verify the exact connection mysqldump is about to use."""
        if job["mysql_auth_type"] == "local_socket":
            target = f"socket={job['mysql_socket'] or '<default>'}"
        else:
            target = f"host={job['mysql_host']} port={job['mysql_port']}"
        if transport is not None:
            profile = transport.profile
            route = f"ssh={profile.username}@{profile.host}:{profile.port}"
        else:
            route = "local"
        self.log(
            f"[MYSQLDUMP][{self.job_id}][CONNECT] route={route} "
            f"auth={job['mysql_auth_type']} {target} "
            f"user={job['mysql_user'] or '<OS account>'}"
        )

        query = (
            "SELECT USER(), CURRENT_USER(), @@hostname, @@port, "
            "COALESCE(DATABASE(), '<none>')"
        )
        client_args = ["--batch", "--skip-column-names", "--execute", query]
        if transport is not None:
            result = self._run_mysql_over_ssh(
                transport, job, "mysql", client_args
            )
            stdout = (result.stdout or b"").decode("utf-8", "ignore")
            stderr = (result.stderr or b"").decode("utf-8", "ignore")
        else:
            connection_args, env = self._mysql_connection(job)
            result = subprocess.run(
                ["mysql", *connection_args, *client_args],
                capture_output=True,
                text=True,
                env=env,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""

        if result.returncode != 0:
            detail = self._process_error(
                stderr or stdout or "unknown mysql client error"
            )
            raise RuntimeError(
                f"mysql connection preflight failed (code={result.returncode}): {detail}"
            )

        fields = stdout.strip().split("\t")
        if len(fields) == 5:
            client_user, authenticated_as, server, port, database = fields
            self.log(
                f"[MYSQLDUMP][{self.job_id}][CONNECTED] "
                f"client_user={client_user} authenticated_as={authenticated_as} "
                f"server={server}:{port} database={database}"
            )
        else:
            self.log(
                f"[MYSQLDUMP][{self.job_id}][CONNECTED] Connection succeeded"
            )

    # ---------------------------------------------------------
    # Dump & file ops
    # ---------------------------------------------------------
    def _dump_database(
        self, job: dict, transport: SSHTransport | None = None
    ) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"{job['filename_prefix']}_{ts}.sql"
        out_path = os.path.join(job["local_tmp"], fname)
        part_path = out_path + ".part"

        # If user specified "all" or "all-databases", switch to --all-databases
        all_dbs = job["database"].lower() in ("all", "all-databases")
        dump_args = []

        if all_dbs:
            dump_args.append("--all-databases")
        else:
            dump_args += ["--databases", job["database"]]

        if job["dump_flags"]:
            dump_args.extend(shlex.split(job["dump_flags"]))

        self.log(f"[MYSQLDUMP][{self.job_id}] Running mysqldump -> {out_path}")
        try:
            with open(part_path, "wb") as f:
                if transport is not None:
                    p = self._run_mysql_over_ssh(
                        transport, job, "mysqldump", dump_args, stdout=f
                    )
                else:
                    connection_args, env = self._mysql_connection(job)
                    p = subprocess.run(
                        ["mysqldump", *connection_args, *dump_args],
                        stdout=f,
                        stderr=subprocess.PIPE,
                        env=env,
                    )
            if p.returncode != 0:
                err = self._process_error(p.stderr)
                raise RuntimeError(f"mysqldump failed (code={p.returncode}): {err}")
            os.replace(part_path, out_path)
        except Exception:
            try:
                os.remove(part_path)
            except FileNotFoundError:
                pass
            raise

        try:
            os.chmod(out_path, 0o600)
        except Exception:
            pass

        return out_path

    def _gzip_file(self, path: str) -> str:
        gz_path = path + ".gz"
        self.log(f"[MYSQLDUMP][{self.job_id}] Compressing -> {gz_path}")

        with open(path, "rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)

        try:
            os.remove(path)
        except Exception:
            pass

        try:
            os.chmod(gz_path, 0o600)
        except Exception:
            pass

        return gz_path

    def _sha256_file(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _write_manifest(self, job: dict, file_path: str, sha: str, started_ts: float) -> str:
        manifest = {
            "job_id": self.job_id,
            "database": job["database"],
            "mysql_host": job["mysql_host"],
            "mysql_port": job["mysql_port"],
            "mysql_auth_type": job["mysql_auth_type"],
            "mysql_via_ssh": job["mysql_via_ssh"],
            "file": os.path.basename(file_path),
            "sha256": sha,
            "bytes": os.path.getsize(file_path),
            "started_at": int(started_ts),
            "finished_at": int(time.time()),
            "compressed": file_path.endswith(".gz"),
        }

        mf_path = file_path + ".manifest.json"
        with open(mf_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        try:
            os.chmod(mf_path, 0o600)
        except Exception:
            pass

        return mf_path

    # ---------------------------------------------------------
    # SSH / rsync
    # ---------------------------------------------------------

    def _remote_mkdir(self, transport: SSHTransport, remote_path: str):
        transport.run(f"mkdir -p -- {shlex.quote(remote_path)}")

    def _rsync_upload(self, transport: SSHTransport, local_file: str, remote_path: str):
        if not os.path.exists(local_file):
            raise FileNotFoundError(local_file)
        transport.rsync(
            local_file,
            remote_path.rstrip("/") + "/",
            ["-a", "-z", "--partial"],
        )

    def _remote_prune(self, transport: SSHTransport, remote_path: str, prune_cfg: dict):
        keep_days = int(prune_cfg.get("keep_days", 0))
        if keep_days <= 0:
            return

        pattern = (prune_cfg.get("pattern") or "*.sql*").strip()

        cmd_str = (
            f"find {shlex.quote(remote_path)} -type f "
            f"-name {shlex.quote(pattern)} -mtime +{keep_days} -delete"
        )

        transport.run(cmd_str, check=False)

    def _local_prune(self, job: dict):
        keep_days = job["remote_prune"]["keep_days"]
        if keep_days <= 0:
            return
        root = Path(job["local_tmp"])
        pattern = re.compile(
            rf"^{re.escape(job['filename_prefix'])}_\d{{8}}_\d{{6}}"
            r"\.sql(?:\.gz)?(?:\.manifest\.json)?$"
        )
        cutoff = time.time() - (keep_days * 86400)
        for candidate in root.iterdir():
            if (
                pattern.fullmatch(candidate.name)
                and candidate.is_file()
                and not candidate.is_symlink()
                and candidate.stat().st_mtime < cutoff
            ):
                candidate.unlink()
