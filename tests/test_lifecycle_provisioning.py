import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    import grp
except ImportError:
    grp = None


ROOT = Path(__file__).resolve().parents[1]


class LifecycleProvisioningTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix" and grp is not None, "Railgun provisions Linux hosts")
    def test_provisioning_keeps_the_lock_inode_and_rejects_a_symlink(self):
        path = ROOT / "phoenix/matrix_gui/modules/railgun/remote_shell.py"
        spec = importlib.util.spec_from_file_location("lifecycle_provision_remote", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        uid, gid = os.getuid(), os.getgid()
        group = grp.getgrgid(gid).gr_name
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "universes"
            script = "\n".join(module._lifecycle_provision_lines())
            script = script.replace("/matrix/universes", str(base))
            script = script.replace("-o root -g root", f"-o {uid} -g {gid}")
            script = script.replace("-o root -g ", f"-o {uid} -g ")
            script = script.replace('chown root:', f'chown {uid}:')
            script = script.replace('"0:0:711"', f'"{uid}:{gid}:711"')
            script = script.replace('"0:$LIFECYCLE_GID:', f'"{uid}:$LIFECYCLE_GID:')

            def provision(universe):
                return subprocess.run(
                    ["/bin/sh", "-c", "set -eu\n" + script],
                    env={**os.environ, "SWARM_USER": group, "UNIVERSE": universe},
                    text=True, capture_output=True,
                )

            first = provision("test-universe")
            self.assertEqual(first.returncode, 0, first.stderr)
            lock = base / "lifecycle/test-universe/lock"
            inode = lock.stat().st_ino
            lock.write_text("existing state", encoding="utf-8")
            second = provision("test-universe")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(lock.stat().st_ino, inode)
            self.assertEqual(lock.read_text(encoding="utf-8"), "existing state")

            bad_dir = base / "lifecycle/symlink-test"
            bad_dir.mkdir(mode=0o750)
            target = Path(temp) / "untouched"
            target.write_text("sentinel", encoding="utf-8")
            (bad_dir / "lock").symlink_to(target)
            bad = provision("symlink-test")
            self.assertNotEqual(bad.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")


if __name__ == "__main__":
    unittest.main()
