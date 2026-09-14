import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


AGENT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "matrixos"
    / "agents"
    / "python_core"
)
sys.path.insert(0, str(AGENT_ROOT))

from rsync_boy.factory.filesystem import rsync_snapshot
from rsync_boy.factory.mysql import mysqldump
from rsync_boy.factory.ssh_transport import SSHTransport, parse_ssh_profile


def _ssh_config():
    return {
        "ssh": {
            "host": "backup.example.test",
            "port": 22,
            "username": "backup",
            "auth_type": "password",
            "password": "secret",
            "trusted_host_fingerprint": "SHA256:abc123=",
        }
    }


class MySQLDumpJobTests(unittest.TestCase):
    def test_remote_mysql_runs_through_pinned_transport_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = {
                **_ssh_config(),
                "mysql": {
                    "host": "127.0.0.1",
                    "username": "matrixswarm_backup",
                    "password": "database-secret",
                    "database": "all",
                },
                "remote_path": "/srv/backups/dragoart/mysql",
                "local_tmp": temp_dir,
                "compress": False,
                "remote_prune": {"keep_days": 0},
            }
            shared = {"context": {"job_id": "dragoart-mysql-full", "config": cfg}}
            messages = []
            runner = mysqldump.MySQLDumpJob(
                lambda message, **kwargs: messages.append(message), shared
            )
            transport = _FakeTransport()

            with mock.patch.object(mysqldump, "SSHTransport", return_value=transport), \
                 mock.patch.object(mysqldump.subprocess, "run") as local_run, \
                 mock.patch.object(
                     mysqldump.time, "strftime", return_value="20260913_120511"
                 ):
                runner.run()

            self.assertEqual("ok", shared["result"])
            self.assertEqual(2, len(transport.script_calls))
            self.assertIn(b"mariadb", transport.script_calls[0][0])
            self.assertIn(b"mysql", transport.script_calls[0][0])
            self.assertIn(b"mariadb-dump", transport.script_calls[1][0])
            self.assertIn(b"mysqldump", transport.script_calls[1][0])
            self.assertNotIn(b"database-secret", transport.script_calls[0][0])
            self.assertNotIn(b"database-secret", transport.script_calls[1][0])
            self.assertEqual(b"complete remote dump", transport.uploaded_contents[0])
            self.assertTrue(any("route=ssh" in message for message in messages))
            local_run.assert_not_called()

    def test_long_client_error_preserves_the_actual_first_line(self):
        message = "unknown option '--bad-flag'\n" + ("usage\n" * 2000)
        detail = mysqldump.MySQLDumpJob._process_error(message.encode())
        self.assertIn("unknown option '--bad-flag'", detail)
        self.assertIn("output shortened", detail)

    def test_blank_local_password_selects_socket_auth(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = {
                "mysql": {
                    "host": "localhost",
                    "username": "root",
                    "password": "",
                    "database": "all",
                },
                "remote_path": "/srv/backups/dragoart/mysql",
                "local_tmp": temp_dir,
                "dump_flags": "--single-transaction --routines",
            }
            job_runner = mysqldump.MySQLDumpJob(lambda *a, **k: None, {"context": {}})
            job = job_runner._validate_and_normalize_cfg(cfg)

            self.assertEqual("local_socket", job["mysql_auth_type"])
            with mock.patch.object(mysqldump.time, "strftime", return_value="20260913_100229"), \
                 mock.patch.object(
                     mysqldump.subprocess,
                     "run",
                     return_value=SimpleNamespace(returncode=0, stderr=b""),
                 ) as run:
                path = job_runner._dump_database(job)

            command = run.call_args.args[0]
            self.assertEqual("mysqldump", command[0])
            self.assertIn("--protocol=socket", command)
            self.assertIn("--all-databases", command)
            self.assertNotIn("-h", command)
            self.assertNotIn("MYSQL_PWD", run.call_args.kwargs["env"])
            self.assertTrue(path.endswith("all_20260913_100229.sql"))

    def test_password_auth_forces_tcp_and_publishes_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = {
                "mysql": {
                    "host": "127.0.0.1",
                    "username": "backup",
                    "password": "secret",
                    "database": "all",
                },
                "remote_path": "/srv/backups/dragoart/mysql",
                "local_tmp": temp_dir,
                "filename_prefix": "dragoart_mysql",
            }
            job_runner = mysqldump.MySQLDumpJob(lambda *a, **k: None, {"context": {}})
            job = job_runner._validate_and_normalize_cfg(cfg)

            def successful_dump(command, **kwargs):
                kwargs["stdout"].write(b"complete dump")
                return SimpleNamespace(returncode=0, stderr=b"")

            with mock.patch.object(mysqldump.time, "strftime", return_value="20260913_110016"), \
                 mock.patch.object(mysqldump.subprocess, "run", side_effect=successful_dump) as run:
                path = job_runner._dump_database(job)

            command = run.call_args.args[0]
            self.assertIn("--protocol=TCP", command)
            self.assertNotIn("secret", command)
            self.assertEqual("secret", run.call_args.kwargs["env"]["MYSQL_PWD"])
            self.assertEqual(b"complete dump", Path(path).read_bytes())
            self.assertFalse(Path(path + ".part").exists())

    def test_failed_dump_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = {
                "mysql": {
                    "host": "127.0.0.1",
                    "username": "backup",
                    "password": "secret",
                    "database": "all",
                },
                "remote_path": "/srv/backups/dragoart/mysql",
                "local_tmp": temp_dir,
            }
            job_runner = mysqldump.MySQLDumpJob(lambda *a, **k: None, {"context": {}})
            job = job_runner._validate_and_normalize_cfg(cfg)

            with mock.patch.object(
                mysqldump.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=2, stderr=b"denied"),
            ):
                with self.assertRaisesRegex(RuntimeError, "denied"):
                    job_runner._dump_database(job)

            self.assertEqual([], list(Path(temp_dir).glob("*.part")))

    def test_remote_password_mode_still_requires_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = {
                "mysql": {
                    "host": "db.example.test",
                    "username": "backup",
                    "database": "all",
                },
                "remote_path": "/srv/backups/mysql",
                "local_tmp": temp_dir,
            }
            job_runner = mysqldump.MySQLDumpJob(lambda *a, **k: None, {"context": {}})
            with self.assertRaisesRegex(ValueError, "mysql_password"):
                job_runner._validate_and_normalize_cfg(cfg)

    def test_local_retention_only_removes_matching_old_dump_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = mysqldump.MySQLDumpJob(lambda *a, **k: None, {"context": {}})
            job = {
                "local_tmp": temp_dir,
                "filename_prefix": "dragoart_mysql",
                "remote_prune": {"keep_days": 14},
            }
            old_dump = Path(temp_dir) / "dragoart_mysql_20260801_000000.sql.gz"
            unrelated = Path(temp_dir) / "do-not-touch.txt"
            recent = Path(temp_dir) / "dragoart_mysql_20260913_231609.sql.gz"
            for path in (old_dump, unrelated, recent):
                path.write_text("data", encoding="utf-8")
            old_time = time.time() - (20 * 86400)
            os.utime(old_dump, (old_time, old_time))
            os.utime(unrelated, (old_time, old_time))

            runner._local_prune(job)

            self.assertFalse(old_dump.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(recent.exists())


class SSHProfileTests(unittest.TestCase):
    def test_password_and_fingerprint_are_retained(self):
        profile = parse_ssh_profile(_ssh_config())
        self.assertEqual("secret", profile.password)
        self.assertEqual("SHA256:abc123=", profile.trusted_host_fingerprint)

    def test_fingerprint_is_mandatory(self):
        config = _ssh_config()
        config["ssh"].pop("trusted_host_fingerprint")
        with self.assertRaisesRegex(ValueError, "trusted_host_fingerprint"):
            parse_ssh_profile(config)

    def test_pull_uses_pinned_transport_without_password_in_arguments(self):
        profile = parse_ssh_profile(_ssh_config())
        transport = SSHTransport(profile)
        transport._known_hosts = "/secure/known_hosts"

        with mock.patch.object(transport, "_require_binary"), \
             mock.patch.object(
                 mysqldump.subprocess,
                 "run",
                 return_value=SimpleNamespace(returncode=0),
             ) as run:
            transport.rsync_from("/sites/", "/backup/snapshots/sites/")

        argv = run.call_args.args[0]
        joined = " ".join(argv)
        self.assertIn("StrictHostKeyChecking=yes", joined)
        self.assertIn("UserKnownHostsFile=/secure/known_hosts", joined)
        self.assertNotIn("secret", argv)
        self.assertEqual("secret", run.call_args.kwargs["env"]["SSHPASS"])


class _FakeTransport:
    def __init__(self):
        self.profile = SimpleNamespace(
            username="backup", host="backup.example.test", port=22
        )
        self.commands = []
        self.rsync_calls = []
        self.script_calls = []
        self.uploaded_contents = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, command, **kwargs):
        self.commands.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    def run_script(self, script, **kwargs):
        self.script_calls.append((script, kwargs))
        stdout = kwargs.get("stdout")
        if hasattr(stdout, "write"):
            stdout.write(b"complete remote dump")
            output = None
        else:
            output = (
                b"matrixswarm_backup@localhost\t"
                b"matrixswarm_backup@localhost\t"
                b"dragoart\t3306\t<none>\n"
            )
        return SimpleNamespace(returncode=0, stdout=output, stderr=b"")

    def path_exists(self, path):
        return path.endswith("/latest")

    def rsync(self, source, destination, options=None):
        self.rsync_calls.append((source, destination, list(options or [])))
        source_path = Path(source)
        if source_path.is_file():
            self.uploaded_contents.append(source_path.read_bytes())
        return SimpleNamespace(returncode=0)

    def rsync_from(self, source, destination, options=None):
        self.rsync_calls.append((source, destination, list(options or [])))
        Path(destination).mkdir(parents=True, exist_ok=True)
        (Path(destination) / "pulled.txt").write_text("from ssh", encoding="utf-8")
        return SimpleNamespace(returncode=0)


class FilesystemSnapshotJobTests(unittest.TestCase):
    def test_remote_source_is_pulled_into_atomic_local_snapshot(self):
        with tempfile.TemporaryDirectory() as destination:
            cfg = {
                **_ssh_config(),
                "source_via_ssh": True,
                "source_path": "/sites",
                "remote_path": destination,
                "snapshot_prefix": "sites",
                "exclude": ["*/public_html/data/cache/***"],
                "remote_prune": {"keep_days": 14},
            }
            shared = {"context": {"job_id": "dragoart-sites", "config": cfg}}
            runner = rsync_snapshot.RsyncSnapshotJob(lambda *a, **k: None, shared)
            transport = _FakeTransport()

            with mock.patch.object(rsync_snapshot, "SSHTransport", return_value=transport), \
                 mock.patch.object(
                     rsync_snapshot.time, "strftime", return_value="20260913_231609"
                 ):
                runner.run()

            snapshot = Path(destination) / "sites_20260913_231609"
            self.assertEqual("ok", shared["result"])
            self.assertEqual(str(snapshot), shared["snapshot"])
            self.assertEqual("from ssh", (snapshot / "pulled.txt").read_text())
            self.assertTrue((snapshot / "snapshot.manifest.json").is_file())
            self.assertEqual(snapshot.name, os.readlink(Path(destination) / "latest"))
            source_pull = transport.rsync_calls[0]
            self.assertEqual("/sites/", source_pull[0])
            self.assertIn("*/public_html/data/cache/***", source_pull[2])
            self.assertNotIn("--delete", source_pull[2])

    def test_snapshot_is_staged_linked_and_published(self):
        with tempfile.TemporaryDirectory() as source:
            cfg = {
                **_ssh_config(),
                "source_path": source,
                "remote_path": "/srv/backups/dragoart/sites",
                "snapshot_prefix": "site",
                "exclude": ["cache/", "*.tmp"],
                "link_dest": True,
                "remote_prune": {"keep_days": 14},
            }
            shared = {"context": {"job_id": "dragoart-sites", "config": cfg}}
            runner = rsync_snapshot.RsyncSnapshotJob(lambda *a, **k: None, shared)
            transport = _FakeTransport()

            with mock.patch.object(rsync_snapshot, "SSHTransport", return_value=transport), \
                 mock.patch.object(
                     rsync_snapshot.time, "strftime", return_value="20260913_100229"
                 ):
                runner.run()

            self.assertEqual("ok", shared["result"])
            self.assertEqual(
                "/srv/backups/dragoart/sites/site_20260913_100229",
                shared["snapshot"],
            )
            source_copy = transport.rsync_calls[0]
            self.assertTrue(source_copy[0].endswith("/"))
            self.assertTrue(source_copy[1].endswith(".partial/"))
            self.assertIn("--link-dest=../latest", source_copy[2])
            self.assertIn("--exclude", source_copy[2])
            publish = "\n".join(command for command, _ in transport.commands)
            self.assertIn("mv -- site_20260913_100229.partial site_20260913_100229", publish)
            self.assertIn(".latest.new latest", publish)

    def test_root_remote_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as source:
            runner = rsync_snapshot.RsyncSnapshotJob(
                lambda *a, **k: None, {"context": {"job_id": "sites"}}
            )
            with self.assertRaisesRegex(ValueError, "non-root"):
                runner._validate_and_normalize_cfg(
                    {"source_path": source, "remote_path": "/"}
                )


if __name__ == "__main__":
    unittest.main()
