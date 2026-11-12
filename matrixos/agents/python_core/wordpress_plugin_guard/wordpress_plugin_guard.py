# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
import hashlib
import shutil
import json
import stat
import tempfile
import threading
import time
from functools import wraps
try:
    import fcntl
except ImportError:  # Windows test environments; MatrixOS runs on Linux.
    fcntl = None
from core.python_core.boot_agent import BootAgent
from core.python_core.utils.swarm_sleep import interruptible_sleep
from core.python_core.utils.crypto_utils import pem_fix
from Crypto.PublicKey import RSA


def _safe_component(value):
    """Accept a single, non-special filename component from an RPC or manifest."""
    if (not isinstance(value, str) or not value or value in (".", "..")
            or "/" in value or "\\" in value or any(ord(c) < 32 for c in value)):
        raise ValueError("Invalid plugin or site name")
    return value


def _serialize_manifest(method):
    """Serialize scans and approvals across threads and POSIX agent processes."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._manifest_lock:
            outer = getattr(self, "_manifest_lock_depth", 0) == 0
            fd = None
            if outer and fcntl is not None:
                directory = _safe_child(self.snapshot_root, self.site_id)
                if not os.path.isdir(directory):
                    if getattr(self, "read_only", False):
                        raise FileNotFoundError("Read-only snapshot directory does not exist")
                    os.makedirs(directory, mode=0o700, exist_ok=True)
                # Linux supports flock on a read-only directory descriptor, so
                # monitoring does not require creating a writable lockfile.
                fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
                try:
                    if not stat.S_ISDIR(os.fstat(fd).st_mode):
                        raise ValueError("Approval lock is not a directory")
                    fcntl.flock(fd, fcntl.LOCK_EX)
                except Exception:
                    os.close(fd)
                    raise
            self._manifest_lock_depth = getattr(self, "_manifest_lock_depth", 0) + 1
            try:
                return method(self, *args, **kwargs)
            finally:
                self._manifest_lock_depth -= 1
                if fd is not None:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    finally:
                        os.close(fd)
    return guarded


def _safe_child(root, name):
    """Reject links and paths that resolve outside the configured directory."""
    name = _safe_component(name)
    if os.path.islink(root):
        raise ValueError("Refusing a linked managed directory")
    base = os.path.realpath(root)
    path = os.path.join(root, name)
    if os.path.islink(path) or os.path.commonpath((base, os.path.realpath(path))) != base:
        raise ValueError("Refusing a linked or out-of-scope plugin path")
    return path


def _raise_walk_error(error):
    raise error


def _read_baseline(path):
    """Read a regular, well-formed baseline without following a final symlink."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Baseline is not a regular file")
        baseline = json.load(stream)
    if not isinstance(baseline, dict) or any(
        not isinstance(name, str) or not isinstance(digest, str)
        or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
        for name, digest in baseline.items()
    ):
        raise ValueError("Invalid plugin baseline")
    return baseline


def _atomic_write_json(path, payload):
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=".plugin-guard-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Persist the rename before advancing a staged approval. MatrixOS runs
        # on POSIX; directory fsync keeps the pending marker durable on power loss.
        if os.name == "posix":
            directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _reject_linked_tree(root):
    """Snapshotting must not read files through links inside a plugin."""
    for directory, subdirs, files in os.walk(root, followlinks=False, onerror=_raise_walk_error):
        for name in subdirs + files:
            if os.path.islink(os.path.join(directory, name)):
                raise ValueError("Refusing symbolic links inside plugin tree")

"""
WordPress Plugin Guard Agent: Monitors the integrity of WordPress plugins
by comparing their current file hashes against a trusted baseline snapshot.
It provides functions to snapshot plugins, scan for changes, quarantine
unauthorized changes, and dispatch alerts and RPC responses.
"""
class Agent(BootAgent):
    """
    The WordPress Plugin Guard Agent (Agent) provides automated File Integrity Monitoring (FIM)
    for WordPress plugins by comparing current file SHA256 hashes against a trusted,
    cryptographically signed baseline manifest.

    The agent's primary functions are:
    1.  **Snapshotting:** Creating and managing SHA256 manifests for approved plugins.
    2.  **Scanning (`_scan_plugins`):** Periodically auditing the plugin directory for:
       * **Integrity Alerts:** Changes (modifications, additions, deletions) to tracked plugins.
       * **Untracked Plugins:** New folders without a baseline manifest.
       * **Missing Plugins:** Tracked plugins that have been removed from disk.
    3.  **Enforcement:**
       * **Quarantine:** Moves untracked/modified plugins to a dedicated quarantine directory if 'enforce' is enabled.
       * **Block-New:** Aggressively deletes untracked plugins immediately if 'block_new' is enabled.
    4.  **Communication:** Dispatches general alerts and responds to GUI panel RPC commands with encrypted and signed status updates.

    **Configuration Context (from `config` section):**
    -   **`plugin_dir`**: `/var/www/html/wordpress/wp-content/plugins` (The directory to monitor).
    -   **`quarantine_dir`**: `/opt/quarantine/wp_plugins` (Path for moved plugins).
    -   **`snapshot_root`**: `/opt/swarm/guard/snapshots` (Root for storing baseline manifests).
    -   **`enforce`**: `False` (Initial state of the automatic quarantine feature).
    -   **`interval`**: `15` (Time in seconds between integrity scans).
    -   **`alert_to_role`**: `hive.alert` (Role for agents receiving critical alerts).
    -   **RPC Services Handled:** `snapshot`, `status`, `list_plugins`, `snapshot_plugin`,
       `snapshot_untracked`, `disapprove_plugin`, `enforce`, `restore_plugin`, `block`,
       `quarantine`, and `delete_quarantined`.
    """
    def __init__(self):
        super().__init__()
        self._manifest_lock = threading.RLock()
        try:
            self.name = "wordpress_plugin_guard"
            cfg = self.tree_node.get("config", {})

            self.AGENT_VERSION = "1.0.0"


            # Configurable paths
            self.plugin_dir = cfg.get("plugin_dir", "/var/www/html/wp-content/plugins")
            self.snapshot_root = cfg.get("snapshot_root", "/opt/swarm/guard/snapshots")
            self.site_id = _safe_component(cfg.get("site_id", "site1"))
            self.quarantine_dir = os.path.join(cfg.get("quarantine_dir", "/opt/quarantine/wp_plugins"), self.site_id)

            self._signing_keys = self.tree_node.get('config', {}).get('security', {}).get('signing', {})
            self._has_signing_keys = bool(self._signing_keys.get('privkey')) and bool(
                self._signing_keys.get('remote_pubkey'))

            if self._has_signing_keys:
                priv_pem = self._signing_keys.get("privkey")
                priv_pem = pem_fix(priv_pem)
                self._signing_key_obj = RSA.import_key(priv_pem.encode() if isinstance(priv_pem, str) else priv_pem)

            self.enforce = bool(cfg.get("enforce", False))
            self.interval = int(cfg.get("interval", 30))
            self.rpc_role = cfg.get("rpc_router_role", "hive.rpc")
            self.alert_role = cfg.get("alert_to_role", None)
            self.report_role = cfg.get("report_to_role", None)
            self.read_only = bool(cfg.get("read_only", False))


            self.block_new = False
            m = self._load_manifest()
            self.block_new = bool(m.get("block_new", self.block_new))
            self.log(f"[PLUGIN-GUARD][INIT] Block-New restored as {self.block_new}", level="INFO")

            m = self._load_manifest()
            self.block_new = bool(m.get("block_new", self.block_new))
            self.enforce = bool(m.get("enforce", self.enforce))
            self.log(f"[PLUGIN-GUARD][INIT] Block-New={self.block_new} Enforce={self.enforce}", level="INFO")

            self._emit_beacon = self.check_for_thread_poke("worker", timeout=90, emit_to_file_interval=10)
            self.last_alerts = {}


        except Exception as e:
            self.log("[PLUGIN-GUARD][INIT]", error=e, level="CRITICAL")
            raise

    def post_boot(self):
        self.log(f"{self.NAME} v{self.AGENT_VERSION} – watching the plugins, because someone has to.")

    # === Helpers ===
    def _sha256_file(self, path):
        """
        Computes the SHA256 hash of a file.

        Args:
            path (str): The full path to the file.

        Returns:
            str: The hexadecimal SHA256 digest.
        """
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()

    def _normalize_folder_name(self, folder):
        """
        Normalizes a plugin folder name by removing common suffixes (e.g.,
        'akismet_1234' becomes 'akismet'), often added during auto-updates.

        Args:
            folder (str): The name of the plugin folder.

        Returns:
            str: The normalized plugin name.
        """
        # WP auto-updates append suffixes (e.g., akismet_1234 → akismet)
        folder = _safe_component(folder)
        return _safe_component(folder.split("_")[0] or folder)

    def _snapshot_plugin(self, plugin_folder, out_path):
        """
        Creates a file integrity manifest (SHA256 hashes) for a single plugin.

        The manifest is a JSON file mapping relative file paths to their hashes.

        Args:
            plugin_folder (str): The full path to the plugin's root directory.
            out_path (str): The file path where the JSON manifest will be saved.

        Returns:
            dict: The generated manifest data.
        """
        _reject_linked_tree(plugin_folder)
        manifest = {}
        for root, dirs, files in os.walk(plugin_folder, onerror=_raise_walk_error):
            for fname in files:
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, plugin_folder).replace("\\", "/")
                manifest[rel] = self._sha256_file(fpath)
        self._ensure_dir(os.path.dirname(out_path))

        def writer():
            _atomic_write_json(out_path, manifest)

        self._safe_write(out_path, writer)

        return manifest

    @_serialize_manifest
    def _snapshot_all_plugins(self):
        """
        Refreshes baseline only for already tracked plugins.
        New/untracked plugins are left out until explicitly approved.
        """
        out_dir = os.path.join(self.snapshot_root, self.site_id)
        self._ensure_dir(out_dir)

        manifest = self._load_manifest()
        tracked = manifest["tracked_plugins"]
        refreshed = 0
        for plugin, approval in list(tracked.items()):
            fpath = _safe_child(self.plugin_dir, plugin)
            if not os.path.isdir(fpath):
                continue
            norm = self._normalize_folder_name(plugin)
            if (not isinstance(approval, dict) or approval.get("normalized") != norm
                    or approval.get("manifest_file") != f"{norm}.json"):
                raise ValueError("Invalid tracked plugin approval")
            out_path = _safe_child(out_dir, f"{norm}.json")
            _read_baseline(out_path)
            self._begin_approval(plugin, norm)
            self._snapshot_plugin(fpath, out_path)
            self._finish_approval(plugin, norm)
            refreshed += 1

        self.log(f"[PLUGIN-GUARD] Refreshed snapshot for {refreshed} tracked plugins at site {self.site_id}")



    def _compare_plugin(self, folder):
        """
        Compares the current files and hashes of a plugin against its
        trusted baseline manifest.

        Args:
            folder (str): The name of the plugin folder to check.

        Returns:
            tuple: (bool, str) - True if clean, False if changes detected,
                   and a string describing the outcome/reason.
        """
        out_dir = os.path.join(self.snapshot_root, self.site_id)
        norm_name = self._normalize_folder_name(folder)
        manifest_path = _safe_child(out_dir, f"{norm_name}.json")
        fpath = _safe_child(self.plugin_dir, folder)

        if not os.path.exists(manifest_path):
            return False, "New or unknown plugin — never trusted."

        baseline = _read_baseline(manifest_path)

        _reject_linked_tree(fpath)
        current = {}
        for root, dirs, files in os.walk(fpath, onerror=_raise_walk_error):
            for fname in files:
                rel = os.path.relpath(os.path.join(root, fname), fpath).replace("\\", "/")
                current[rel] = self._sha256_file(os.path.join(root, fname))

        changed = [k for k in current if k in baseline and current[k] != baseline[k]]
        added   = [k for k in current if k not in baseline]
        deleted = [k for k in baseline if k not in current]

        if changed or added or deleted:
            return False, "Plugin files were changed since last trusted baseline."
        return True, "Clean"

    # === Core Scan ===
    @_serialize_manifest
    def _scan_plugins(self):
        """
        The main scan logic. Iterates through all plugins, compares against manifests,
        and alerts on anomalies:
          - Changed files
          - New/untrusted plugin folders (no manifest)
          - Trusted plugins missing from disk
        Also quarantines if enforcement is enabled.
        """
        manifest = self._load_manifest()
        pending_approvals = manifest.get("pending_approvals", {})
        if not isinstance(pending_approvals, dict):
            raise ValueError("Invalid pending approval state")
        try:
            # refresh persisted states first
            self.block_new = bool(manifest.get("block_new", self.block_new))
            self.enforce = bool(manifest.get("enforce", self.enforce))
        except Exception as e:
            self.log(f"[PLUGIN-GUARD][SCAN] Failed to refresh states: {e}", level="WARN")


        try:
            entries = os.listdir(self.plugin_dir)
            existing = set(entries)

            # --- cleanup stale manifest records ---
            changed = False

            for name in list(manifest["tracked_plugins"].keys()):
                if name not in existing:
                    self.log(f"[PLUGIN-GUARD][CLEANUP] 🧹 Removing stale tracked record for {name}", level="INFO")
                    del manifest["tracked_plugins"][name]
                    changed = True

            for name in list(manifest["untracked_plugins"].keys()):
                if name not in existing:
                    self.log(f"[PLUGIN-GUARD][CLEANUP] 🧹 Removing stale untracked record for {name}", level="INFO")
                    del manifest["untracked_plugins"][name]
                    changed = True

            if changed:
                if getattr(self, "read_only", False):
                    self.log("[PLUGIN-GUARD][READONLY] Stale entries ignored for this scan; manifest unchanged.", level="INFO")
                else:
                    self._save_manifest(manifest)
                    self.log(f"[PLUGIN-GUARD][CLEANUP] Manifest pruned of stale entries.", level="INFO")

        except Exception as e:
            self.log("[PLUGIN-GUARD] Failed to list plugin dir", error=e)
            return

        try:
            out_dir = os.path.join(self.snapshot_root, self.site_id)
            self._ensure_dir(out_dir)

            # Collect known manifests
            snapshots = {f[:-5] for f in os.listdir(out_dir)
                         if f.endswith(".json") and not f.startswith(".")}

            # Keep every folder: normalized names can collide during updates.
            # Do not silently ignore a linked plugin, which could hide a change.
            current_plugins = []
            for folder in entries:
                path = os.path.join(self.plugin_dir, folder)
                if os.path.islink(path):
                    self.log(f"[PLUGIN-GUARD][DIR-AUDIT] Linked plugin entry rejected: {folder}", level="WARN")
                    if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"linked:{folder}"):
                        self.drop_alert({"plugin": folder, "path": path, "reason": "Linked plugin entry cannot be inspected safely.", "action": "linked_plugin", "enforce": self.enforce, "timestamp": int(time.time())})
                    continue
                if os.path.isdir(path):
                    current_plugins.append((self._normalize_folder_name(folder), folder))

            normalized_counts = {}
            for norm, _folder in current_plugins:
                normalized_counts[norm] = normalized_counts.get(norm, 0) + 1

            # === Step 1: Check each folder on disk ===
            for norm, folder in current_plugins:
                fpath = os.path.join(self.plugin_dir, folder)
                if norm in pending_approvals:
                    self.log(f"[PLUGIN-GUARD][DIR-AUDIT] Plugin approval incomplete: {folder}", level="WARN")
                    if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"pending:{folder}"):
                        self.drop_alert({"plugin": folder, "path": fpath, "reason": "Plugin approval did not complete; review or retry before trusting it.", "action": "pending_approval", "enforce": self.enforce, "timestamp": int(time.time())})
                    continue
                if normalized_counts[norm] > 1 and norm in snapshots:
                    self.log(f"[PLUGIN-GUARD][DIR-AUDIT] Ambiguous plugin baseline: {folder}", level="WARN")
                    if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"collision:{folder}"):
                        self.drop_alert({"plugin": folder, "path": fpath, "reason": "Multiple plugin folders share one baseline; review before trusting or removing either.", "action": "baseline_collision", "enforce": self.enforce, "timestamp": int(time.time())})
                    continue
                try:
                    manifest_path = _safe_child(out_dir, f"{norm}.json")
                    has_baseline = os.path.lexists(manifest_path)
                    if has_baseline:
                        _read_baseline(manifest_path)
                except (ValueError, OSError, UnicodeError):
                    self.log(f"[PLUGIN-GUARD][DIR-AUDIT] Unsafe plugin baseline: {folder}", level="ERROR")
                    if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"unsafe-baseline:{folder}"):
                        self.drop_alert({"plugin": folder, "path": fpath, "reason": "Baseline is invalid, unreadable, linked, or outside the snapshot directory.", "action": "unsafe_baseline", "enforce": self.enforce, "timestamp": int(time.time())})
                    # A broken baseline is not proof that the plugin is bad.
                    # Leave it in place for operator review, even in enforce mode.
                    continue

                approval = manifest.get("tracked_plugins", {}).get(folder)
                if has_baseline and (not isinstance(approval, dict)
                                     or approval.get("normalized") != norm
                                     or approval.get("manifest_file") != f"{norm}.json"):
                    self.log(f"[PLUGIN-GUARD][DIR-AUDIT] Baseline has no matching approval: {folder}", level="WARN")
                    if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"unregistered-baseline:{folder}"):
                        self.drop_alert({"plugin": folder, "path": fpath, "reason": "Baseline exists without approval for this exact folder; review before trusting or removing it.", "action": "unregistered_baseline", "enforce": self.enforce, "timestamp": int(time.time())})
                    continue

                if has_baseline:
                    try:
                        clean, reason = self._compare_plugin(folder)
                    except (ValueError, OSError, UnicodeError) as exc:
                        self.log(f"[PLUGIN-GUARD][SCAN] Could not verify {folder}", error=exc, level="ERROR")
                        if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"unverifiable:{folder}"):
                            self.drop_alert({"plugin": folder, "path": fpath, "reason": "Plugin integrity could not be verified; review before taking action.", "action": "integrity_unverifiable", "enforce": self.enforce, "timestamp": int(time.time())})
                        continue
                    if not clean:
                        # Only a completed comparison can justify enforcement.
                        verified_change = reason == "Plugin files were changed since last trusted baseline."
                        action = "plugin_modified" if verified_change else "integrity_unverifiable"
                        if verified_change and self.enforce and not getattr(self, "read_only", False):
                            try:
                                self._quarantine(folder, fpath)
                                action = "auto_quarantine"
                            except Exception as exc:
                                self.log(f"[PLUGIN-GUARD][ENFORCE] Failed to quarantine {folder}", error=exc, level="ERROR")
                                action = "quarantine_failed"
                        self.log(f"[PLUGIN-GUARD][SCAN] {folder}: {action}", level="WARN")
                        if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"integrity:{folder}:{action}"):
                            self.drop_alert({"plugin": folder, "path": fpath, "reason": reason, "action": action, "enforce": self.enforce, "timestamp": int(time.time())})
                    continue

                if not has_baseline:
                    info = {
                        "plugin": folder,
                        "path": fpath,
                        "reason": "Plugin folder present but no baseline manifest exists.",
                        "enforce": self.enforce,
                        "timestamp": int(time.time())
                    }

                    self.log(f"[PLUGIN-GUARD][DIR-AUDIT] 🚨 Untrusted plugin detected: {folder}", level="WARN")

                    # prioritize block-new over enforce, but never both
                    if self.block_new and not getattr(self, "read_only", False) and not getattr(self, "_suppress_alerts", False):
                        try:
                            shutil.rmtree(fpath)
                            self.log(f"[PLUGIN-GUARD][BLOCK] ❌ Deleted untracked plugin {folder} instantly.",
                                     level="CRITICAL")
                            self.drop_alert({
                                "plugin": folder,
                                "path": fpath,
                                "reason": "Untracked plugin deleted under Block-New enforcement.",
                                "action": "auto_delete",
                                "enforce": self.enforce,
                                "timestamp": int(time.time())
                            })
                            continue
                        except Exception as be:
                            self.log(f"[PLUGIN-GUARD][BLOCK][ERROR] Failed to delete {folder}: {be}", level="ERROR")


                    if self.enforce and not getattr(self, "read_only", False):

                        try:

                            self._quarantine(folder, fpath)

                            self.log(f"[PLUGIN-GUARD][ENFORCE] 🚨 Quarantined untracked plugin {folder}.", level="WARN")

                            if not getattr(self, "_suppress_alerts", False) and self.should_alert(
                                    f"{folder}:auto_quarantine"):
                                alert_info = dict(info)

                                alert_info["action"] = "auto_quarantine"

                                alert_info["reason"] = "Untracked plugin quarantined under Enforcement mode."

                                self.drop_alert(alert_info)

                            continue


                        except Exception as qe:

                            self.log(f"[PLUGIN-GUARD][ENFORCE][ERROR] Failed to quarantine {folder}: {qe}", level="ERROR")

                            if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"{folder}:quarantine_failed"):
                                alert_info = dict(info)
                                alert_info["action"] = "quarantine_failed"
                                alert_info["reason"] = f"Failed to quarantine untracked plugin: {qe}"
                                self.drop_alert(alert_info)

                    else:
                        self.log(f"[PLUGIN-GUARD][BLOCK] Enforcement inactive or read-only; leaving {folder} in place.", level="INFO")

                    if not getattr(self, "_suppress_alerts", False) and self.should_alert(folder):
                        self.drop_alert(info)

            present_norms = {norm for norm, _folder in current_plugins}
            for norm, plugin in pending_approvals.items():
                _safe_component(norm)
                _safe_component(plugin)
                if norm not in present_norms:
                    self.log(f"[PLUGIN-GUARD][DIR-AUDIT] Approval incomplete for missing plugin: {plugin}", level="WARN")
                    if not getattr(self, "_suppress_alerts", False) and self.should_alert(f"pending:{plugin}"):
                        self.drop_alert({"plugin": plugin, "reason": "Plugin approval did not complete and its folder is missing; review before retrying.", "action": "pending_approval", "enforce": self.enforce, "timestamp": int(time.time())})

            # === Step 2: Check for deleted plugins (manifest exists but no folder) ===
            for snap in snapshots:
                found = any(self._normalize_folder_name(f) == snap for f in entries)
                if not found:
                    info = {
                        "plugin": snap,
                        "reason": "Trusted plugin missing from disk.",
                        "timestamp": int(time.time())
                    }
                    self.log(f"[PLUGIN-GUARD][DIR-AUDIT] ⚠️ Trusted plugin missing from disk: {snap}", level="WARN")
                    if self.should_alert(snap):
                        self.drop_alert(info)

        except Exception as e:
            self.log("[PLUGIN-GUARD] Failed to list plugin dir", error=e)
            return

    @_serialize_manifest
    def cmd_toggle_block(self, content, packet, identity=None):
        req = packet.get("content", {})
        enable = bool(req.get("block_new", not self.block_new))
        self.block_new = enable

        manifest = self._load_manifest()
        manifest["block_new"] = self.block_new
        self._save_manifest(manifest)

        if self.block_new:
            # warn operator before the scan loop enforces
            self.log("[PLUGIN-GUARD][WARN] ⚠️ Block-New enabled. "
                     "All untracked plugins will be deleted on next scan.", level="WARN")

            self._suppress_alerts = True
            try:
                self.drop_alert({
                    "plugin": "system",
                    "path": self.plugin_dir,
                    "reason": "Operator enabled Block-New mode. "
                              "All untracked plugins will be deleted on next scan.",
                    "enforce": self.enforce,
                    "action": "mode_change",
                    "timestamp": int(time.time())
                })
            finally:
                self._suppress_alerts = False

        else:
            self.log("[PLUGIN-GUARD][INFO] Block-New disabled. "
                     "Untracked plugins will no longer be automatically deleted.", level="INFO")

        self._cmd_list_alert_status(
            req.get("session_id", "none"),
            req.get("token"),
            req.get("return_handler", "plugin_guard.panel.update"),
        )

    def _quarantine(self, folder, fpath):
        """
        Moves an unauthorized or modified plugin folder to the configured
        quarantine directory and logs the action.

        Args:
            folder (str): The name of the plugin folder.
            fpath (str): The full path to the plugin to be moved.
        """
        if getattr(self, "read_only", False):
            raise PermissionError("Plugin guard is in read-only mode")
        self._ensure_dir(self.quarantine_dir)
        qpath = _safe_child(self.quarantine_dir, f"{_safe_component(folder)}_{int(time.time())}")
        if os.path.lexists(qpath):
            raise FileExistsError("Quarantine destination already exists")
        try:
            shutil.move(fpath, qpath)
            self.log(f"[PLUGIN-GUARD] Quarantined {folder} → {qpath}")
        except Exception as e:
            fallback = f"{qpath}.failcopy"
            self.log(f"[PLUGIN-GUARD][QUARANTINE][FAIL] Move failed: {e}; attempting fallback copy → {fallback}",
                     level="ERROR")
            try:
                # Preserve links rather than copying arbitrary targets outside
                # the plugin when rename fails across filesystems.
                shutil.copytree(fpath, fallback, symlinks=True)
                shutil.rmtree(fpath)
                self.log(f"[PLUGIN-GUARD][QUARANTINE] Fallback succeeded: copied to {fallback}", level="WARN")
            except Exception as final_e:
                self.log(f"[PLUGIN-GUARD][QUARANTINE][FATAL] Fallback copy also failed: {final_e}", level="CRITICAL")
                raise RuntimeError(f"Could not quarantine plugin {folder}") from final_e

    def should_alert(self, key):
        """
        Implements a basic one-time alert mechanism: only alerts if the key
        (the plugin folder name) has not been alerted on before in this session.

        Args:
            key (str): The unique identifier (plugin folder name).

        Returns:
            bool: True if an alert should be sent, False otherwise.
        """
        if key in self.last_alerts:
            return False
        self.last_alerts[key] = time.time()
        return True

    # === Alert Dispatch (Gatekeeper style) ===
    def drop_alert(self, info: dict):
        """
        Constructs and dispatches a general notification alert packet to agents
        with the configured 'alert_to_role'.

        Args:
            info (dict): A dictionary containing plugin details (plugin name,
                         path, reason, and enforcement status).
        """
        try:
            endpoints = self.get_nodes_by_role(self.alert_role)
            if not endpoints:
                self.log("[PLUGIN-GUARD][ALERT] No alert-compatible agents found.", level="WARN")
                return

            pk1 = self.get_delivery_packet("standard.command.packet")
            pk2 = self.get_delivery_packet("notify.alert.general")

            msg_text = (
                f"🧹 WordPress Plugin Guard Alert\n\n"
                f"• Plugin: {info.get('plugin')}\n"
                f"• Path: {info.get('path')}\n"
                f"• Reason: {info.get('reason')}\n"
                f"• Action: {info.get('action','detected')}\n"
                f"• Hash: {info.get('hash')}\n"
                f"• Enforce: {info.get('enforce')}\n"
                f"• Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            pk2.set_data({
                "msg": msg_text,
                "universal_id": self.command_line_args.get("universal_id", "unknown"),
                "level": "critical",
                "cause": "Unauthorized WordPress Plugin",
                "origin": self.command_line_args.get("universal_id", "unknown")
            })

            self.log_proto(
                f"ALERT dispatched for plugin {info.get('plugin')} at {info.get('path')}",
                level="WARN",
                block="DROP_ALERT"
            )

            pk1.set_packet(pk2, "content")
            for ep in endpoints:
                pk1.set_payload_item("handler", ep.get_handler())
                self.pass_packet(pk1, ep.get_universal_id())

            details = {
                "plugin": info.get("plugin"),
                "path": info.get("path"),
                "reason": info.get("reason"),
                "action": info.get("action", "detected"),
                "hash": info.get("hash"),
                "enforce": info.get("enforce"),
                "timestamp": info.get("timestamp", int(time.time()))
            }
            metrics = {"plugin_guard": info}
            self.send_status_report('plugin_integrity_alert', 'CRITICAL', details, metrics)

        except Exception as e:
            self.log(error=e, block="drop_alert", level="ERROR")


    # === RPC Commands ===
    def cmd_list_plugins(self, content, packet, identity=None):
        """
        RPC command to list the names of all plugin folders currently present
        on the disk. The result is broadcasted back via `_broadcast_output`.
        """
        req = packet.get("content", {})
        session_id = req.get("session_id", "none")
        token = req.get("token", str(int(time.time())))
        return_handler = req.get("return_handler", "plugin_guard.panel.update")

        plugins = []
        for folder in os.listdir(self.plugin_dir):
            fpath = os.path.join(self.plugin_dir, folder)
            if os.path.isdir(fpath):
                plugins.append(folder)

        self._broadcast_output(
            {"plugins": plugins},
            handler=return_handler,
            session_id=session_id,
            token=token
        )

    @_serialize_manifest
    def cmd_enforce(self, content, packet, identity=None):
        """
        RPC command to toggle enforcement mode on or off.
        Persists state in manifest and notifies operator.
        """
        try:
            req = packet.get("content", {})
            # If enforce is included, use it; otherwise flip current state
            if "enforce" in req:
                enable = bool(req.get("enforce"))
            else:
                enable = not self.enforce

            self.enforce = enable
            manifest = self._load_manifest()
            manifest["enforce"] = self.enforce
            self._save_manifest(manifest)
            self.log(f"[PLUGIN-GUARD] Persisted enforce={self.enforce} to manifest", level="INFO")

            # operator log + alert
            if self.enforce:
                self.log("[PLUGIN-GUARD][WARN] ⚔️ Enforcement enabled. "
                         "Untracked or modified plugins will be moved to quarantine on next scan.",
                         level="WARN")

                try:
                    self._suppress_alerts = True
                    self.drop_alert({
                        "plugin": "system",
                        "path": self.plugin_dir,
                        "reason": "Operator enabled Enforcement mode. "
                                  "Untracked or modified plugins will be quarantined on next scan.",
                        "enforce": self.enforce,
                        "action": "mode_change",
                        "timestamp": int(time.time())
                    })
                finally:
                    self._suppress_alerts = False


            else:
                self.log("[PLUGIN-GUARD][INFO] Enforcement disabled. "
                         "No automatic quarantines will occur.", level="INFO")

            # send updated state to panel
            return_handler = req.get("return_handler", "plugin_guard.panel.update")
            session_id = req.get("session_id", "none")
            token = req.get("token", str(int(time.time())))
            self._cmd_list_alert_status(session_id, token, return_handler)

        except Exception as e:
            self.log("[PLUGIN-GUARD][ERROR] cmd_enforce failed", error=e)

    @_serialize_manifest
    def cmd_snapshot_plugin(self, content, packet, identity=None):
        """
        Approve and snapshot a single plugin folder (like 'git add <plugin>').
        """
        req = packet.get("content", {})
        plugin = req.get("plugin")
        session_id = req.get("session_id", "none")
        token = req.get("token", str(int(time.time())))
        return_handler = req.get("return_handler", "plugin_guard.panel.update")

        self._suppress_alerts = True
        try:
            if not plugin:
                self.log("[PLUGIN-GUARD] No plugin specified for approval", level="WARN")
                return

            plugin = _safe_component(plugin)
            fpath = _safe_child(self.plugin_dir, plugin)
            if not os.path.isdir(fpath):
                self.log(f"[PLUGIN-GUARD] Plugin {plugin} not found on disk", level="WARN")
                return

            norm_name = self._normalize_folder_name(plugin)

            out_dir = os.path.join(self.snapshot_root, self.site_id)
            self._ensure_dir(out_dir)
            norm_name = self._normalize_folder_name(plugin)
            manifest_path = _safe_child(out_dir, f"{norm_name}.json")

            self._begin_approval(plugin, norm_name)
            self._snapshot_plugin(fpath, manifest_path)
            self._finish_approval(plugin, norm_name)
            self.log(f"[PLUGIN-GUARD][SNAPSHOT] Approved plugin {plugin} → {manifest_path}")

            self._cmd_list_alert_status(session_id, token, return_handler)
        except (ValueError, OSError) as exc:
            self.log("[PLUGIN-GUARD][SNAPSHOT] Rejected or failed to snapshot plugin", error=exc, level="ERROR")
        finally:
            self._suppress_alerts = False

    def _manifest_path(self):
        return _safe_child(os.path.join(self.snapshot_root, self.site_id), ".manifest.json")

    @_serialize_manifest
    def _begin_approval(self, plugin, norm):
        """Persist an unresolved marker before changing a shared baseline."""
        plugin, norm = _safe_component(plugin), _safe_component(norm)
        manifest = self._load_manifest()
        pending = manifest.setdefault("pending_approvals", {})
        if not isinstance(pending, dict):
            raise ValueError("Invalid pending approval state")
        if norm in pending and pending[norm] != plugin:
            raise ValueError("Another plugin has a pending approval for this baseline")
        for other, approval in manifest.get("tracked_plugins", {}).items():
            if other != plugin and isinstance(approval, dict) and approval.get("normalized") == norm:
                raise ValueError("Another tracked plugin uses this baseline")
        pending[norm] = plugin
        self._save_manifest(manifest)

    @_serialize_manifest
    def _finish_approval(self, plugin, norm):
        """Publish trust only after its baseline has been saved successfully."""
        manifest = self._load_manifest()
        pending = manifest.get("pending_approvals")
        if not isinstance(pending, dict) or pending.get(norm) != plugin:
            raise ValueError("Pending plugin approval changed during snapshot")
        self._register_plugin(manifest, plugin, norm)
        manifest.setdefault("untracked_plugins", {}).pop(plugin, None)
        manifest["untracked_plugins"].pop(norm, None)
        del pending[norm]
        self._save_manifest(manifest)

    def _load_manifest(self):

        path = self._manifest_path()

        r={
            "site": self.site_id,
            "tracked_plugins": {},
            "untracked_plugins": {},
            "block_new": False
        }

        if os.path.exists(path):
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                    raise ValueError("Plugin manifest is not a regular file")
                data = json.load(f)
            if "untracked_plugins" not in data:
                data["untracked_plugins"] = {}
            if "block_new" not in data:
                data["block_new"] = False
            if "enforce" not in data:
                data["enforce"] = False
            if not isinstance(data.get("pending_approvals", {}), dict):
                raise ValueError("Invalid pending approval state")
            return data

        return r

    def _save_manifest(self, manifest):
        path = self._manifest_path()
        self._ensure_dir(os.path.dirname(path))

        self._safe_write(
            path,
            lambda: _atomic_write_json(path, manifest)
        )

    @_serialize_manifest
    def cmd_snapshot_untracked(self, content, packet, identity=None):
        """
        Approve and snapshot all untracked plugin folders (like 'git add .').
        """
        self._suppress_alerts = True
        try:
            req = packet.get("content", {})
            session_id = req.get("session_id", "none")
            token = req.get("token", str(int(time.time())))
            return_handler = req.get("return_handler", "plugin_guard.panel.update")

            out_dir = os.path.join(self.snapshot_root, self.site_id)
            self._ensure_dir(out_dir)
            tracked = self._load_manifest().get("tracked_plugins", {})
            if not isinstance(tracked, dict):
                raise ValueError("Invalid tracked plugin state")
            approved = []
            skipped = []
            candidates = []
            counts = {}
            for folder in os.listdir(self.plugin_dir):
                path = os.path.join(self.plugin_dir, folder)
                if os.path.islink(path):
                    skipped.append(folder)
                    continue
                fpath = _safe_child(self.plugin_dir, folder)
                if not os.path.isdir(fpath):
                    continue
                norm_name = self._normalize_folder_name(folder)
                candidates.append((folder, norm_name, fpath))
                counts[norm_name] = counts.get(norm_name, 0) + 1
            for folder, norm_name, fpath in candidates:
                if folder in tracked:
                    continue
                if counts[norm_name] > 1:
                    skipped.append(folder)
                    self.log(f"[PLUGIN-GUARD][SNAPSHOT] Ambiguous plugin baseline; skipped {folder}", level="WARN")
                    continue
                manifest_path = _safe_child(out_dir, f"{norm_name}.json")
                self._begin_approval(folder, norm_name)
                self._snapshot_plugin(fpath, manifest_path)
                self._finish_approval(folder, norm_name)
                approved.append(folder)
                self.log(f"[PLUGIN-GUARD][SNAPSHOT] Approved new plugin {folder} → {manifest_path}")

            self._broadcast_output(
                {"approved_plugins": approved, "skipped_plugins": skipped, "snapshot_done": True},
                handler=return_handler,
                session_id=session_id,
                token=token
            )
        finally:
            self._suppress_alerts = False

    @_serialize_manifest
    def cmd_snapshot_plugins(self, content, packet, identity=None):
        """
        RPC command to refresh snapshot of all *tracked* plugins.
        Does NOT auto-trust new/untracked ones.
        """
        self._snapshot_all_plugins()

        req = packet.get("content", {})
        session_id = req.get("session_id", "none")
        token = req.get("token", str(int(time.time())))
        return_handler = req.get("return_handler", "plugin_guard.panel.update")

        plugins = []
        for folder in os.listdir(self.plugin_dir):
            fpath = os.path.join(self.plugin_dir, folder)
            if os.path.isdir(fpath):
                plugins.append(folder)

        self._broadcast_output(
            {"plugins": plugins, "snapshot_done": True},
            handler=return_handler,
            session_id=session_id,
            token=token
        )

    @_serialize_manifest
    def cmd_disapprove_plugin(self, content, packet, identity=None):
        """
        Remove a plugin from tracked list.
        If 'manual_quarantine' flag is True, also move it to quarantine.
        """
        self._suppress_alerts = True
        try:
            req = packet.get("content", {})
            plugin = req.get("plugin")
            do_quarantine = bool(req.get("manual_quarantine", False))

            session_id = req.get("session_id", "none")
            token = req.get("token", str(int(time.time())))
            return_handler = req.get("return_handler", "plugin_guard.panel.update")

            if not plugin:
                self.log("[PLUGIN-GUARD] No plugin specified for disapproval", level="WARN")
                return

            plugin = _safe_component(plugin)

            manifest = self._load_manifest()
            tracked = manifest.get("tracked_plugins", {})
            untracked = manifest.get("untracked_plugins", {})

            # --- Drop from tracked
            if plugin in tracked:
                norm = _safe_component(tracked[plugin]["normalized"])
                manifest_file = _safe_child(os.path.join(self.snapshot_root, self.site_id), f"{norm}.json")
                if os.path.exists(manifest_file):
                    os.remove(manifest_file)
                del tracked[plugin]
                self.log(f"[PLUGIN-GUARD][SNAPSHOT] Disapproved {plugin}, baseline removed.", level="INFO")

            # --- Manifest cleanup
            if plugin in untracked:
                del untracked[plugin]
            self._save_manifest(manifest)

            # --- Push full refresh ---
            self._cmd_list_alert_status(session_id, token, return_handler)

        except Exception as e:
            self.log("[PLUGIN-GUARD][ERROR] cmd_disapprove_plugin failed", error=e)
        finally:
            self._suppress_alerts = False


    @_serialize_manifest
    def cmd_quarantine_plugin(self, content, packet, identity=None):
        """
        Move a plugin (tracked or untracked) directly to quarantine.
        """
        try:
            if getattr(self, "read_only", False):
                raise PermissionError("Plugin guard is in read-only mode")
            req = packet.get("content", {})
            plugin = req.get("plugin")
            session_id = req.get("session_id", "none")
            token = req.get("token", str(int(time.time())))
            return_handler = req.get("return_handler", "plugin_guard.panel.update")

            if not plugin:
                self.log("[PLUGIN-GUARD] No plugin specified for quarantine", level="WARN")
                return

            plugin = _safe_component(plugin)
            fpath = _safe_child(self.plugin_dir, plugin)
            if not os.path.isdir(fpath):
                self.log(f"[PLUGIN-GUARD][QUARANTINE] Plugin {plugin} not found in plugins directory.", level="WARN")
                return

            self._ensure_dir(self.quarantine_dir)
            qpath = _safe_child(self.quarantine_dir, f"{plugin}_{int(time.time())}")
            if os.path.lexists(qpath):
                raise FileExistsError("Quarantine destination already exists")

            try:
                shutil.move(fpath, qpath)
                self.log(f"[PLUGIN-GUARD][QUARANTINE] Moved {plugin} → {qpath}", level="WARN")
            except Exception as qe:
                self.log(f"[PLUGIN-GUARD][ERROR] Failed to move {plugin} to quarantine: {qe}", level="ERROR")
                return

            # update manifest: remove from both tracked/untracked
            manifest = self._load_manifest()
            if plugin in manifest.get("tracked_plugins", {}):
                del manifest["tracked_plugins"][plugin]
            if plugin in manifest.get("untracked_plugins", {}):
                del manifest["untracked_plugins"][plugin]
            self._save_manifest(manifest)

            self._cmd_list_alert_status(session_id, token, return_handler)

        except Exception as e:
            self.log("[PLUGIN-GUARD][ERROR] cmd_quarantine_plugin failed", error=e)

    @_serialize_manifest
    def cmd_delete_quarantined_plugin(self, content, packet, identity=None):
        """
        Permanently delete a quarantined plugin folder.
        """
        try:
            if getattr(self, "read_only", False):
                raise PermissionError("Plugin guard is in read-only mode")
            req = packet.get("content", {})
            plugin = req.get("plugin")
            session_id = req.get("session_id", "none")
            token = req.get("token", str(int(time.time())))
            return_handler = req.get("return_handler", "plugin_guard.panel.update")

            if not plugin:
                self.log("[PLUGIN-GUARD] No plugin specified for deletion.", level="WARN")
                return

            qpath = _safe_child(self.quarantine_dir, plugin)
            if not os.path.isdir(qpath):
                self.log(f"[PLUGIN-GUARD][DELETE] Plugin {plugin} not found in quarantine.", level="WARN")
                return

            try:
                shutil.rmtree(qpath)
                self.log(f"[PLUGIN-GUARD][DELETE] Permanently deleted quarantined plugin {plugin}", level="CRITICAL")
            except Exception as de:
                self.log(f"[PLUGIN-GUARD][ERROR] Failed to delete {plugin}: {de}", level="ERROR")
                return

            # cleanup manifest in case any ghost entries linger
            manifest = self._load_manifest()
            for key in ["tracked_plugins", "untracked_plugins"]:
                if plugin in manifest.get(key, {}):
                    del manifest[key][plugin]
            self._save_manifest(manifest)

            # refresh panel
            self._cmd_list_alert_status(session_id, token, return_handler)

        except Exception as e:
            self.log("[PLUGIN-GUARD][ERROR] cmd_delete_quarantined_plugin failed", error=e)

    @_serialize_manifest
    def cmd_restore_plugin(self, content, packet, identity=None):
        """
        Move a quarantined plugin back to the active plugins directory.
        """
        self._suppress_alerts = True
        try:
            if getattr(self, "read_only", False):
                raise PermissionError("Plugin guard is in read-only mode")
            req = packet.get("content", {})
            plugin = req.get("plugin")
            session_id = req.get("session_id", "none")
            token = req.get("token", str(int(time.time())))
            return_handler = req.get("return_handler", "plugin_guard.panel.update")

            plugin = _safe_component(plugin)
            qsrc = _safe_child(self.quarantine_dir, plugin)
            if not os.path.exists(qsrc):
                self.log(f"[PLUGIN-GUARD][RESTORE] Plugin {plugin} not found in quarantine.", level="WARN")
                return

            dst = _safe_child(self.plugin_dir, self._normalize_folder_name(plugin))
            if os.path.lexists(dst):
                raise FileExistsError("Restore destination already exists")
            if not os.path.isdir(qsrc):
                raise ValueError("Quarantined plugin is not a directory")
            norm_name = self._normalize_folder_name(plugin)
            manifest_path = _safe_child(os.path.join(self.snapshot_root, self.site_id), f"{norm_name}.json")
            self._begin_approval(norm_name, norm_name)
            shutil.move(qsrc, dst)
            self.log(f"[PLUGIN-GUARD][RESTORE] Restored {plugin} → {dst}")

            # --- Auto-trust restored plugin ---
            fpath = dst

            if os.path.isdir(fpath):
                self._snapshot_plugin(fpath, manifest_path)
                self._finish_approval(norm_name, norm_name)
                self.log(f"[PLUGIN-GUARD][RESTORE] Auto-trusted {plugin} after restore.")

            self._cmd_list_alert_status(session_id, token, return_handler)

        except Exception as e:
            self.log("[PLUGIN-GUARD][ERROR] cmd_restore_plugin failed", error=e)
        finally:
            self._suppress_alerts = False


    def cmd_list_alert_status(self, content, packet, identity=None):
        """
        RPC command to list plugin status:
          - tracked_clean
          - tracked_alerts (failed integrity)
          - untracked (no manifest)
          - quarantined
        """
        try:
            req = packet.get("content", {})
            session_id = req.get("session_id", "none")
            token = req.get("token", str(int(time.time())))
            return_handler = req.get("return_handler", "plugin_guard.panel.update")

            self._cmd_list_alert_status(session_id, token, return_handler)
        except Exception as e:
            self.log(error=e, block="cmd_list_alert_status")

    @_serialize_manifest
    def _cmd_list_alert_status(self, session_id="none", token=None, return_handler="plugin_guard.panel.update"):
        """
        Internal version of cmd_list_alert_status so other commands can trigger a full panel refresh.
        """
        out_dir = os.path.join(self.snapshot_root, self.site_id)
        self._ensure_dir(out_dir)

        manifest = self._load_manifest()
        tracked = list(manifest["tracked_plugins"].keys())
        untracked_meta = manifest["untracked_plugins"]
        pending_approvals = manifest.get("pending_approvals", {})
        if not isinstance(pending_approvals, dict):
            raise ValueError("Invalid pending approval state")

        tracked_clean, tracked_alerts, untracked = [], {}, []

        entries = os.listdir(self.plugin_dir)
        baseline_names = {f[:-5] for f in os.listdir(out_dir) if f.endswith(".json") and not f.startswith(".")}
        normalized_counts = {}
        for folder in entries:
            path = os.path.join(self.plugin_dir, folder)
            if not os.path.islink(path) and os.path.isdir(path):
                try:
                    norm = self._normalize_folder_name(folder)
                except ValueError:
                    continue
                normalized_counts[norm] = normalized_counts.get(norm, 0) + 1

        for folder in entries:
            fpath = os.path.join(self.plugin_dir, folder)
            if os.path.islink(fpath):
                tracked_alerts[folder] = {"reason": "Linked plugin entry cannot be inspected safely."}
                continue
            if not os.path.isdir(fpath):
                continue

            try:
                norm = self._normalize_folder_name(folder)
            except ValueError:
                tracked_alerts[folder] = {"reason": "Plugin name is invalid and cannot be inspected safely."}
                continue

            if norm in pending_approvals:
                tracked_alerts[folder] = {"reason": "Plugin approval did not complete; review or retry before trusting it."}
                continue

            if normalized_counts.get(norm, 0) > 1 and norm in baseline_names:
                tracked_alerts[folder] = {"reason": "Multiple plugin folders share one baseline; review before trusting either."}
                continue

            if folder in tracked:
                approval = manifest["tracked_plugins"].get(folder)
                if (not isinstance(approval, dict) or approval.get("normalized") != norm
                        or approval.get("manifest_file") != f"{norm}.json"):
                    tracked_alerts[folder] = {"reason": "Plugin approval metadata is invalid; review before trusting it."}
                    continue
                try:
                    ok, reason = self._compare_plugin(folder)
                except (OSError, ValueError, UnicodeError) as exc:
                    self.log(f"[PLUGIN-GUARD][SCAN] Could not verify {folder}", error=exc, level="ERROR")
                    ok, reason = False, "Plugin integrity could not be verified."
                if ok:
                    tracked_clean.append(folder)
                else:
                    tracked_alerts[folder] = {"reason": reason}
                continue

            # outsider
            untracked.append(folder)
            if folder not in untracked_meta or not untracked_meta[folder].get("alerted"):
                info = {
                    "plugin": folder,
                    "path": fpath,
                    "reason": "New plugin folder present but not tracked",
                    "timestamp": int(time.time()),
                    "enforce": self.enforce,
                }
                self.log(f"[PLUGIN-GUARD][DIR-AUDIT] 🚨 Untracked plugin detected: {folder}", level="WARN")

                if not getattr(self, "_suppress_alerts", False) and self.should_alert(folder):
                    self.drop_alert(info)

                untracked_meta[folder] = {
                    "first_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "alerted": True,
                }
                if not getattr(self, "read_only", False):
                    self._save_manifest(manifest)

        for norm, plugin in pending_approvals.items():
            _safe_component(norm)
            _safe_component(plugin)
            if plugin not in tracked_alerts and plugin not in tracked_clean:
                tracked_alerts[plugin] = {"reason": "Plugin approval did not complete; review or retry before trusting it."}

        quarantined = []
        if os.path.exists(self.quarantine_dir):
            for folder in os.listdir(self.quarantine_dir):
                qpath = os.path.join(self.quarantine_dir, folder)
                if os.path.isdir(qpath):
                    quarantined.append(folder)

        scan_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self._broadcast_output(
            {
                "tracked_clean": tracked_clean,
                "tracked_alerts": tracked_alerts,
                "untracked": untracked,
                "quarantined_plugins": quarantined,
                "block_new": self.block_new,
                "enforce_state": self.enforce,
                "last_scan": scan_time,
            },
            handler=return_handler,
            session_id=session_id,
            token=token,
        )

    def _broadcast_output(self, output, handler="plugin_guard.panel.update",session_id="none", token=None):
        """
        Encrypts, signs, and dispatches an RPC response packet to the
        configured RPC router role.

        Args:
            output (dict): The data payload to send back.
            handler (str): The handler to be executed on the receiving end.
            session_id (str): The session identifier for the request.
            token (str): A token for tracking the response.
        """
        try:

            payload = {
                    "session_id": session_id,
                    "token": token,
                    **output,
                    "timestamp": int(time.time())
                }

            # Send securely via BootAgent's crypto pipeline
            self.crypto_reply(
                response_handler=handler,
                payload=payload,
                session_id=session_id,
                token=token,
                rpc_role=self.rpc_role
            )

            self.log("[PLUGIN-GUARD] Broadcasted panel output")


        except Exception as e:
            self.log("[PLUGIN-GUARD][ERROR] Broadcast failed", error=e)

    def send_status_report(self, status, severity, details, metrics=None):
        """
        Sends a structured status event packet to the configured role for forensic ingestion.
        Mirrors Gatekeeper's style.
        """
        try:
            if not self.report_role:
                self.log("[PLUGIN-GUARD] No report_to_role configured, skipping status report.", level='WARN')
                return

            endpoints = self.get_nodes_by_role(self.report_role)
            if not endpoints:
                self.log(f"[PLUGIN-GUARD] No endpoints found for role '{self.report_role}'", level='WARN')
                return

            pk_inner = self.get_delivery_packet("standard.status.event.packet")
            pk_inner.set_data({
                "source_agent": self.command_line_args.get("universal_id", "plugin_guard"),
                "service_name": "wordpress.plugins",
                "status": status,
                "details": details,
                "severity": severity,
                "metrics": metrics or {}
            })

            pk = self.get_delivery_packet("standard.command.packet")
            pk.set_data({"handler": "cmd_ingest_status_report"})
            pk.set_packet(pk_inner, "content")

            for ep in endpoints:
                pk.set_payload_item("handler", ep.get_handler())
                self.pass_packet(pk, ep.get_universal_id())

            self.log(f"[PLUGIN-GUARD] Structured status report sent to role '{self.report_role}'", level='INFO')

        except Exception as e:
            self.log(f"[PLUGIN-GUARD][ERROR] send_status_report failed: {e}", level='ERROR')

    def _ensure_dir(self, path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            self.log(f"[PLUGIN-GUARD][ERROR] Failed to create dir: {path} – {e}", level="ERROR")
            raise

    def _register_plugin(self, manifest, plugin, norm_name):
        manifest["tracked_plugins"][plugin] = {
            "normalized": norm_name,
            "manifest_file": f"{norm_name}.json",
            "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "approved_by": "commander"
        }

    def _safe_write(self, path, write_func, op_name="write", *args, **kwargs):
        """
        Attempts a safe write operation. Alerts the operator on permission issues
        or disk I/O errors that prevent successful file writes.

        Args:
            path (str): Path being written to (for alert/log context)
            write_func (callable): The function performing the write
            *args, **kwargs: Passed directly to write_func
        """
        if self.read_only:
            self.log(f"[PLUGIN-GUARD][READONLY] 🔒 Write skipped for {path} (read-only mode)", level="WARN")
            raise PermissionError("Plugin guard is in read-only mode")

        try:
            return write_func(*args, **kwargs)
        except PermissionError as pe:
            msg = f"🚫 Permission denied while writing {path} failed on {path}"
            self.log(f"[PLUGIN-GUARD][PERM] {msg}: {pe}", level="ERROR")
            self.drop_alert({
                "plugin": "system",
                "path": path,
                "reason": msg,
                "action": "permission_error",
                "enforce": self.enforce,
                "timestamp": int(time.time())
            })
            raise
        except OSError as oe:
            msg = f"💾 OS error while writing {path}: {oe.strerror}"
            self.log(f"[PLUGIN-GUARD][IO] {msg}", level="ERROR")
            self.drop_alert({
                "plugin": "system",
                "path": path,
                "reason": msg,
                "action": "write_failed",
                "enforce": self.enforce,
                "timestamp": int(time.time())
            })
            raise
        except Exception as e:
            msg = f"⚠️ Unexpected error while writing {path}: {e}"
            self.log(f"[PLUGIN-GUARD][IO] {msg}", level="ERROR")
            self.drop_alert({
                "plugin": "system",
                "path": path,
                "reason": msg,
                "action": "write_exception",
                "enforce": self.enforce,
                "timestamp": int(time.time())
            })
            raise

    # === Worker ===
    def worker(self, config=None, identity=None):
        """
        The main loop for the agent. It runs the integrity scan (`_scan_plugins`)
        and then sleeps for the configured interval.

        Args:
            config (dict, optional): Configuration passed to the worker.
            identity (IdentityObject, optional): The agent's identity.
        """
        self._emit_beacon()
        self._scan_plugins()
        interruptible_sleep(self, self.interval)

if __name__ == "__main__":
    agent = Agent()
    agent.boot()
