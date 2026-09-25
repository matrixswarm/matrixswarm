"""Vault-backed, cancellable source discovery for Clown Car deployment."""

from pathlib import Path
from PyQt6.QtWidgets import QMessageBox
from matrix_gui.core.dialog.agent_root_check_dialog import AgentRootCheckDialog
from matrix_gui.core.class_lib.paths.agent_root_selector import AgentSourceSelection
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton


class AgentRootValidator:
    def __init__(self, directive_staging, cached_paths=None, parent=None):
        self.directive_staging = directive_staging
        self.vcs = VaultCoreSingleton.get()
        self.cached_paths = [p for p in (cached_paths or []) if isinstance(p, str) and p]
        self.parent = parent

    def run(self):
        """Return a source root only after every node has a verified src; None means abort."""
        try:
            selection = AgentSourceSelection(self.directive_staging)
            for candidate in self.cached_paths:
                try:
                    selection.add_directory(candidate)
                except (OSError, ValueError):
                    continue  # Stale vault paths must lead to selection, not abort.
                if not selection.missing_agents:
                    break

            while True:
                selection.refresh()
                if not selection.missing_agents:
                    selection.apply()
                    self._cache(selection.roots)
                    print(f"[CLOWN-CAR][OK] Verified {len(selection.sources)} sources across {len(selection.roots)} directories.")
                    return selection.roots[0]

                initial = next((p for p in self.cached_paths if Path(p).is_dir()), None)
                dialog = AgentRootCheckDialog(
                    self.directive_staging, self.parent, selection=selection, initial_path=initial,
                )
                if not dialog.exec_check():
                    return None
                # Recheck after the dialog closes; deleted/unreadable files prompt again.
        except Exception as exc:
            QMessageBox.critical(self.parent, "Agent Source Verification Failed", str(exc))
            return None

    def _cache(self, verified_roots):
        """Persist only contributing directories after the entire selection succeeds."""
        roots = list(verified_roots)
        for path in self.vcs.data.get("agent_roots", []):
            if isinstance(path, str) and path and path not in roots:
                roots.append(path)
        self.vcs.patch("last_agent_path", verified_roots[0])
        self.vcs.patch("agent_roots", roots)
