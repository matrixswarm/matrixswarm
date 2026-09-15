"""Deployment-time RsyncBoy SSH profile resolution regressions."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PHOENIX = ROOT / "phoenix"
sys.path.insert(0, str(PHOENIX))

from matrix_gui.swarm_workspace.cls_lib.deployment.rsync_boy_profiles import (  # noqa: E402
    RsyncBoyProfileError,
    inject_rsync_boy_ssh_profiles,
)


def ssh_record():
    return {
        "label": "CDN assets",
        "host": "push.example.test",
        "port": 22,
        "username": "backup",
        "auth_type": "password",
        "password": "deployment-only-secret",
        "trusted_host_fingerprint": "SHA256:examplePinnedFingerprint",
        "unrelated_registry_field": "do-not-stage",
    }


def rsync_node(profile="cdn-assets-01"):
    job = {
        "id": "cdn-assets",
        "factory": "filesystem.rsync_snapshot.RsyncSnapshotJob",
        "config": {},
    }
    if profile:
        job["ssh_profile"] = profile
    return {"name": "rsync_boy", "config": {"jobs": [job]}}


class RsyncBoyProfileDeploymentTests(unittest.TestCase):
    def test_only_referenced_profile_is_staged_with_runtime_credentials(self):
        nodes = {"one": rsync_node()}
        registry = {
            "cdn-assets-01": ssh_record(),
            "unused": {**ssh_record(), "password": "unused-secret"},
        }

        count = inject_rsync_boy_ssh_profiles(nodes, registry)

        self.assertEqual(count, 1)
        pool = nodes["one"]["config"]["ssh_profiles"]
        self.assertEqual(list(pool), ["cdn-assets-01"])
        self.assertEqual(pool["cdn-assets-01"]["password"], "deployment-only-secret")
        self.assertNotIn("unrelated_registry_field", pool["cdn-assets-01"])
        self.assertNotIn("unused-secret", repr(nodes))

    def test_legacy_primary_profile_requires_no_pool(self):
        nodes = {"one": rsync_node(profile="")}
        nodes["one"]["config"]["ssh_profiles"] = {
            "stale": {"password": "must-be-removed"}
        }

        self.assertEqual(inject_rsync_boy_ssh_profiles(nodes, {}), 0)
        self.assertNotIn("ssh_profiles", nodes["one"]["config"])

    def test_missing_or_unpinned_profile_blocks_deployment(self):
        with self.assertRaisesRegex(RsyncBoyProfileError, "missing from Registry"):
            inject_rsync_boy_ssh_profiles({"one": rsync_node()}, {})
        unpinned = ssh_record()
        unpinned["trusted_host_fingerprint"] = ""
        with self.assertRaisesRegex(RsyncBoyProfileError, "trusted SHA256"):
            inject_rsync_boy_ssh_profiles(
                {"one": rsync_node()}, {"cdn-assets-01": unpinned}
            )


if __name__ == "__main__":
    unittest.main()
