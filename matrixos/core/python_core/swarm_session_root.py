import os
import stat
import uuid
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from .safe_paths import _component, child_directory, open_base

class SwarmSessionRoot:
    def __init__(self, universe: str, base_path: str, reboot_uuid: str = None, mode: str = "new"):
        self.universe = universe
        self.base = base_path
        self.reboot_uuid = reboot_uuid or datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        self.runtime_root = Path(self.base) / "universes" / "runtime" / universe / self.reboot_uuid
        self.static_root = Path(self.base) / "universes" / "static" / universe / self.reboot_uuid

        self.runtime_comm_path = self.runtime_root / "comm"
        self.runtime_pod_path = self.runtime_root / "pod"
        self.static_comm_path = self.static_root / "comm"
        self.static_pod_path = self.static_root / "pod"

        if mode == "new":
            # full fresh start
            self.create_directories()
            self.set_latest_symlinks()

        elif mode == "reuse":
            # Cleanup happens only after CoreSpawner has validated the reuse
            # paths and the authenticated directive's active agent IDs.
            print(f"[SWARM][REUSE] Reused existing session: {self.reboot_uuid}.")

    def create_directories(self):
        _component(self.universe)
        _component(self.reboot_uuid)
        with ExitStack() as stack:
            base_fd = open_base(self.base, create=True)
            stack.callback(os.close, base_fd)
            universes = stack.enter_context(child_directory(base_fd, "universes", create=True, traverse_only=True))
            for kind in ("runtime", "static"):
                with ExitStack() as branch:
                    root = branch.enter_context(child_directory(universes, kind, create=True, traverse_only=True))
                    universe = branch.enter_context(child_directory(root, self.universe, create=True))
                    boot = branch.enter_context(child_directory(universe, self.reboot_uuid, create=True))
                    for name in ("comm", "pod"):
                        with child_directory(boot, name, create=True):
                            pass

    def set_latest_symlinks(self):
        with ExitStack() as stack:
            base_fd = open_base(self.base)
            stack.callback(os.close, base_fd)
            universes = stack.enter_context(child_directory(base_fd, "universes", traverse_only=True))
            for kind in ("runtime", "static"):
                with ExitStack() as branch:
                    root = branch.enter_context(child_directory(universes, kind, traverse_only=True))
                    universe = branch.enter_context(child_directory(root, self.universe))
                    self._create_symlink(universe, self.reboot_uuid)

    def _create_symlink(self, universe_fd: int, target_uuid: str):
        _component(target_uuid)
        try:
            existing = os.stat("latest", dir_fd=universe_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISLNK(existing.st_mode):
                raise ValueError("Refusing to replace a non-symlink latest entry")
            if os.readlink("latest", dir_fd=universe_fd) == target_uuid:
                return
        temporary = f".latest.{uuid.uuid4().hex}"
        os.symlink(target_uuid, temporary, dir_fd=universe_fd)
        try:
            os.replace(temporary, "latest", src_dir_fd=universe_fd, dst_dir_fd=universe_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=universe_fd)
            except FileNotFoundError:
                pass
