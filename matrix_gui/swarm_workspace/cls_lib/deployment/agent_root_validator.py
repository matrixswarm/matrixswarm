# Commander Edition
from pathlib import Path
from PyQt6.QtWidgets import QMessageBox
from matrix_gui.core.dialog.agent_root_check_dialog import AgentRootCheckDialog
from matrix_gui.core.class_lib.paths.agent_root_selector import AgentRootSelector
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton


class AgentRootValidator:
    """
    Commander Edition – Full Clown-Car orchestration class.
    Ensures all agents referenced in directive_staging are found on disk.
    Loops until:
        ✅ All agents verified, OR
        ❌ User cancels.
    """

    def __init__(self, directive_staging, cached_paths=None):
        self.directive_staging = directive_staging
        self.vcs = VaultCoreSingleton.get()
        self.cached_paths = [Path(p) for p in (cached_paths or []) if p]
        self.verified_root = None
        self.missing_agents = []

    # ---------------------------------------------------------
    def run(self):
        """
        Begin verification loop.
        Returns verified root path (str) or None if cancelled.
        """
        try:
            print("[CLOWN-CAR][TRACE] Starting AgentRootValidator...")

            # Try cached paths first, in order
            for candidate in self.cached_paths:
                if candidate.exists():
                    if self._validate(candidate):
                        self._cache(candidate)
                        return str(candidate)

            # Enter persistent loop
            while True:
                dlg = AgentRootCheckDialog(self.directive_staging)
                new_path = dlg.exec_check()

                if not new_path:
                    QMessageBox.warning(
                        None,
                        "Cancelled",
                        "Deployment cancelled — agent source directory required."
                    )
                    return None

                candidate = Path(new_path)
                if not candidate.exists():
                    QMessageBox.warning(None, "Invalid Path", f"{new_path} does not exist.")
                    continue

                if self._validate(candidate):
                    self._cache(candidate)
                    return str(candidate)

                # Still missing, loop again
                agents = ", ".join(self.missing_agents)
                QMessageBox.warning(
                    None,
                    "Agents Missing",
                    f"The following agents could not be located:\n\n{agents}\n\nPlease select a new directory."
                )

        except Exception as e:
            QMessageBox.critical(None, "AgentRootValidator Failed", str(e))
            print(f"[AgentRootValidator][ERROR] {e}")

    # ---------------------------------------------------------
    def _validate(self, candidate_path: Path) -> bool:
        """
        Validate that all agents in directive_staging exist under candidate_path.
        Returns True if all found, False otherwise.
        """
        print(f"[CLOWN-CAR][TRACE] Validating agents under {candidate_path}")
        try:
            self.missing_agents = (
                AgentRootSelector.verify_all_sources(self.directive_staging, str(candidate_path)) or []
            )

            if not self.missing_agents:
                print(f"[CLOWN-CAR][OK] All agents verified at {candidate_path}")
                self.verified_root = candidate_path
                return True

            print(f"[CLOWN-CAR][WARN] Missing agents: {self.missing_agents}")
            return False

        except Exception as e:
            print(f"[CLOWN-CAR][ERROR] Validation failed: {e}")
            self.missing_agents = ["validation_error"]
            return False

    # ---------------------------------------------------------
    def _cache(self, verified_path: Path):
        """Cache verified agent root in vault for future deployments."""
        print(f"[CLOWN-CAR] Caching verified agent root: {verified_path}")

        verified_str = str(verified_path)

        roots = list(self.vcs.data.get("agent_roots", []))
        if verified_str in roots:
            roots.remove(verified_str)
        roots.insert(0, verified_str)

        self.vcs.data["last_agent_path"] = verified_str
        self.vcs.data["agent_roots"] = roots

        self.vcs.patch("last_agent_path", verified_str)
        self.vcs.patch("agent_roots", roots)