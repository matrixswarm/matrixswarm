"""RsyncBoy job clipboard format and validation regressions."""

from pathlib import Path
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PHOENIX = ROOT / "phoenix"
sys.path.insert(0, str(PHOENIX))

from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.rsync_boy_clipboard import (
    CLIPBOARD_FORMAT,
    FILESYSTEM_FACTORY,
    MYSQL_FACTORY,
    JobClipboardError,
    decode_jobs,
    encode_jobs,
)


def filesystem_job(job_id="sites"):
    return {
        "id": job_id,
        "enabled": True,
        "factory": FILESYSTEM_FACTORY,
        "schedule": {"interval_sec": 86400, "run_on_boot": True},
        "config": {
            "source_via_ssh": True,
            "source_path": "/sites",
            "remote_path": "/backup/snapshots/sites",
            "snapshot_prefix": "sites",
            "exclude": ["*/public_html/data/cache/***"],
            "link_dest": True,
            "preserve_hard_links": True,
            "preserve_acls": True,
            "preserve_xattrs": True,
            "remote_prune": {"keep_days": 30},
        },
    }


def mysql_job():
    return {
        "id": "mysql-full",
        "enabled": False,
        "factory": MYSQL_FACTORY,
        "schedule": {"interval_sec": 43200, "run_on_boot": False},
        "config": {
            "remote_path": "/srv/backups/mysql/",
            "local_tmp": "/backup/mysql_dumps",
            "dump_flags": "--single-transaction --quick",
            "mysql_via_ssh": True,
            "compress": True,
            "filename_prefix": "dragoart_mysql",
            "remote_prune": {"keep_days": 14},
        },
    }


class RsyncBoyClipboardTests(unittest.TestCase):
    def test_round_trip_preserves_all_supported_job_details(self):
        jobs = [mysql_job(), filesystem_job()]
        jobs[1]["ssh_profile"] = "cdn-assets-01"
        payload = encode_jobs(jobs)
        self.assertEqual(decode_jobs(payload), jobs)
        self.assertEqual(json.loads(payload)["format"], CLIPBOARD_FORMAT)

    def test_export_drops_non_job_fields_and_credentials(self):
        candidate = filesystem_job()
        candidate["config"]["ssh"] = {
            "password": "clipboard-secret",
            "private_key": "private-key-secret",
        }
        candidate["config"]["mysql"] = {"password": "database-secret"}
        candidate["future_field"] = "not-in-version-one"

        payload = encode_jobs([candidate])
        self.assertNotIn("clipboard-secret", payload)
        self.assertNotIn("private-key-secret", payload)
        self.assertNotIn("database-secret", payload)
        self.assertNotIn("future_field", payload)

    def test_profile_selector_is_portable_but_profile_secrets_are_not(self):
        candidate = filesystem_job()
        candidate["ssh_profile"] = "cdn-assets-01"
        candidate["ssh_profiles"] = {
            "cdn-assets-01": {"password": "never-export-this"}
        }
        payload = encode_jobs([candidate])
        self.assertEqual(decode_jobs(payload)[0]["ssh_profile"], "cdn-assets-01")
        self.assertNotIn("never-export-this", payload)

    def test_invalid_bundle_is_rejected_before_import(self):
        valid = json.loads(encode_jobs([filesystem_job()]))
        invalid_documents = [
            {},
            {**valid, "version": 2},
            {**valid, "jobs": [filesystem_job(), filesystem_job()]},
            {**valid, "jobs": [{**filesystem_job(), "factory": "evil.Factory"}]},
            {**valid, "jobs": [{**filesystem_job(), "id": "../unsafe"}]},
        ]
        for document in invalid_documents:
            with self.subTest(document=document):
                with self.assertRaises(JobClipboardError):
                    decode_jobs(json.dumps(document))

        with self.assertRaises(JobClipboardError):
            decode_jobs("not json")


if __name__ == "__main__":
    unittest.main()
