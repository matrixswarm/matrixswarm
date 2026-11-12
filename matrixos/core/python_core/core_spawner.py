"""
Core Spawner for the MatrixSwarm Framework.
Authored by Daniel F MacDonald and ChatGPT aka The Generals
Gemini, code enhancements and Docstrings
This module defines the CoreSpawner class, which is the central engine for
instantiating, managing, and terminating agents within the MatrixSwarm. It handles
the entire lifecycle of an agent, from setting up its dedicated communication
channels and runtime environment to launching it as a secure, isolated process.

Key Responsibilities:
-   **Filesystem Scaffolding**: Creates the necessary directory structures for
    inter-agent communication (`comm` channels) and temporary runtime execution
    (`pod` directories).
-   **Secure Environment Preparation**: Utilizes mixins to handle the creation
    of a secure, encrypted environment for each agent, passing sensitive data
    like cryptographic keys through environment variables.
-   **Agent Lifecycle Management**: Spawns agents from source files, verifies
    their integrity via hash checking, logs their creation, and provides
    mechanisms for their graceful or forceful termination.
-   **Configuration and Trust Management**: Ingests path configurations, trust
    assets (keys), and agent-specific directives to ensure each agent is
-   spawned with the correct context and permissions.
"""
import os
import sys
import hashlib
from pathlib import Path
# Add the directory containing this script to the PYTHONPATH
current_directory = os.path.dirname(os.path.abspath(__file__))  # Directory of the current script
if current_directory not in sys.path:
    sys.path.insert(0, current_directory)

import json
import base64
import uuid
import shutil
import stat
import subprocess
import fcntl
import select
import traceback
import psutil
from datetime import datetime
from class_lib.file_system.file_system_builder import FileSystemBuilder
from core.python_core.path_manager import PathManager
from core.python_core.lifecycle_fence import GENERATION_ENV
from core.python_core.reuse_cleanup import require_directory, prepare_reused_runtime, purge_runtime_paths, validate_reuse_paths, validate_agent_ids
from core.python_core.safe_paths import runtime_directory, static_directory, read_agent_source, child_directory, write_file_at, append_file_at, trusted_shared_agent_root, trusted_shared_core_root, trusted_agent_import_root
from core.python_core.class_lib.logging.logger import Logger
from core.python_core.mixin.core_spawn_secure import CoreSpawnerSecureMixin
from core.python_core.mixin.ghost_vault import build_encrypted_spawn_env


def _publish_boot_record(path, record):
    """Publish complete boot metadata without exposing a partial JSON file."""
    path = Path(path)
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing_mode = None
    else:
        if not stat.S_ISREG(existing.st_mode):
            raise ValueError(f"Unsafe existing boot record: {path}")
        existing_mode = stat.S_IMODE(existing.st_mode)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    created = False
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     existing_mode if existing_mode is not None else 0o666)
        created = True
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            if existing_mode is not None:
                os.fchmod(file.fileno(), existing_mode)
            json.dump(record, file, indent=4)
        os.replace(temporary, path)
    finally:
        if created:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


class CoreSpawner(CoreSpawnerSecureMixin):
    """
    Manages the creation, lifecycle, and termination of MatrixSwarm agents.

    This class orchestrates the entire process of bringing an agent online.
    It prepares the agent's filesystem, sets up secure communication channels,
    and launches the agent process with a secure, encrypted environment.
    """
    def __init__(self, universe, base_path, reboot_uuid=None, python_site=None, detected_python=None, booting=False, args=None, active_agent_ids=None):
        """
        Initializes the CoreSpawner instance.

        Args:
            path_manager (PathManager, optional): An instance of PathManager for
                resolving framework paths. If not provided, a new one is created.
                Defaults to None.
            site_root_path (str, optional): The root path of the website or
                application being managed by the swarm. Defaults to
                '/site/your_site_fallback_path'.
            python_site (str, optional): The path to the Python site-packages
                directory. Defaults to None.
            detected_python (str, optional): The path to the Python executable
                to be used for spawning agents. Defaults to None.
            install_path (str, optional): The root installation path of the
                MatrixSwarm framework. Defaults to None.
        """
        super().__init__()

        self._keychain = {}
        self.verbose=False
        self.debug = False
        self.rug_pull = False
        self.protect_memory = False
        self.lifecycle_generation = os.environ.get(GENERATION_ENV)
        self.matrix_universal_id = "matrix"

        self.python_site=python_site
        self.python_exec= detected_python

        # Defines the default directory structure for an agent's communication channel.
        self.default_comm_file_spec = [
            {"name": "directive", "type": "d", "content": None},
            {"name": "hello.moto", "type": "d", "content": None},
            {"name": "payload", "type": "d", "content": None},
            {"name": "incoming", "type": "d", "content": None},
            {"name": "codex", "type": "d", "content": None},
            {"name": "queue", "type": "d", "content": None},
            {"name": "stack", "type": "d", "content": None, "meta": "Long - term mission chaining"},
            {"name": "replies", "type": "d", "content": None, "meta": "stack / Long - term mission chaining"},
            {"name": "broadcast", "type": "d", "content": None, "meta": "Shared folder for swarms with listeners"},
            {"name": "config", "type": "d", "content": None, "meta": "Updated configs go here"},
        ]

        self.pm = None

        #called from boot_agent
        if not bool(booting):

            self.pm = PathManager(universe, base_path, reboot_uuid)

        else:

            universe_root = Path(base_path) / "universes" / "runtime" / universe
            universe_exists = require_directory(universe_root, missing_ok=True)

            # if neither option set args.reboot_id or not args.reboot_new
            if not args.reboot_id and not args.reboot_new:


                # try to reuse latest
                candidates = []
                for path in universe_root.iterdir() if universe_exists else ():
                    if path.name.replace("_", "").isdigit():
                        require_directory(path)
                        candidates.append(path.name)

                if candidates:
                    latest_uuid = sorted(candidates)[-1]
                    validate_reuse_paths(base_path, universe, latest_uuid)
                    retired, signals = prepare_reused_runtime(base_path, universe, latest_uuid, active_agent_ids or ())
                    self.pm = PathManager(universe, base_path, reboot_uuid=latest_uuid, mode="reuse")
                    if retired:
                        print(f"[SPAWNER] Retired obsolete agent channels to {retired}")
                    if signals:
                        print(f"[SPAWNER] Retired old agent signals to {signals}")
                    print(f"[SPAWNER] ♻️ Reusing latest reboot_uuid: {latest_uuid}")

            #reuse a given reboot_uuid
            elif args.reboot_id:

                validate_reuse_paths(base_path, universe, args.reboot_id)
                retired, signals = prepare_reused_runtime(base_path, universe, args.reboot_id, active_agent_ids or ())
                self.pm = PathManager(universe, base_path, reboot_uuid=args.reboot_id, mode="resume")
                if retired:
                    print(f"[SPAWNER] Retired obsolete agent channels to {retired}")
                if signals:
                    print(f"[SPAWNER] Retired old agent signals to {signals}")
                print(f"[SPAWNER] Resuming reboot UUID: {args.reboot_id}")


            #fallback to newboot
            if not isinstance(self.pm, PathManager):
                self.pm = PathManager(universe, base_path, mode="new")
                print(f"[SPAWNER] New reboot_uuid: {self.pm.reboot_uuid}")

            # handle --clean
            if args.clean:
                print("[SPAWNER] Cleaning runtime directories…")
                purge_runtime_paths(base_path, universe, self.pm.reboot_uuid)
                print("[SPAWNER] Runtime purge complete (static preserved)")

    def _cleanup(self):
        # clean old pods before continuing
        pod_path = Path(self.pm.session.runtime_pod_path)
        if require_directory(pod_path, missing_ok=True):
            for pod in pod_path.iterdir():
                if pod.is_symlink():
                    raise ValueError(f"Unsafe link in reused pod directory: {pod}")
                if pod.is_dir():
                    shutil.rmtree(pod)
            print(f"[SPAWNER] Cleared stale pods in {pod_path}")

    def set_keys(self, key_dict: dict):
        """
        Injects multiple cryptographic keys and trust assets at once.

        Args:
            key_dict (dict): A dictionary containing key names and their values
                             (e.g., matrix_pub, swarm_key, security_box).
        """
        self._keychain = key_dict

    def set_key(self, name: str, key):
        """
        Sets a single cryptographic key or trust asset by name.

        Args:
            name (str): The name of the key (e.g., 'swarm_key', 'matrix_pub').
            key: The key material.
        """
        if not hasattr(self, "_keychain"):
            self._keychain = {}
        self._keychain[name] = key

    def set_verbose(self, verbose):
        """
        Enables or disables verbose output for spawned processes.

        Args:
            verbose (bool): If True, spawned agents will print to stdout/stderr.
        """
        self.verbose = bool(verbose)

    def set_rug_pull(self, rug_pull:bool=True):

        self.rug_pull = bool(rug_pull)

    def set_debug(self, debug):
        """
        Enables or disables debug mode for spawned agents.

        Args:
            debug (bool): If True, agents may run with additional debugging logic.
        """
        self.debug = bool(debug)

    def set_protect_memory(self, enabled=True):
        """Require Linux to mark spawned agents non-dumpable before boot."""
        self.protect_memory = bool(enabled)

    def set_matrix_universal_id(self, universal_id):
        """Set the authoritative root address propagated to every child."""
        value = str(universal_id or "").strip()
        if not value:
            raise ValueError("Matrix universal_id is required")
        self.matrix_universal_id = value

    def reset_hard(self):
        """
        Performs a hard reset, wiping all agent communication and runtime directories.

        Warning: This is a destructive operation that deletes all transient agent
        data.
        """
        #NEED TO WAIT UNTIL ALL PROCESSES HAVE COMPLETED
        for root in [self.pm.resolve('runtime_comm'), self.pm.resolve("runtime_pod")]:
            for folder in os.listdir(root):
                folder_path = os.path.join(root, folder)
                if os.path.isdir(folder_path):
                    shutil.rmtree(folder_path)

        print("[SPAWNER] Hard reset complete.")

    def verify_soft(self):
        """
        Ensures that the base communication and runtime directories exist.
        """
        for root in [self.pm.resolve('runtime_comm'), self.pm.resolve("runtime_pod")]:
            os.makedirs(root, exist_ok=True)
            print(f"[SPAWNER] Verified structure: {root}")

    def ensure_comm_channel(self, universal_id, file_spec, agent_directive=None):
        """
        Creates or verifies the communication directory structure for a given agent.

        It uses a FileSystemBuilder to create the default folder layout and then
        merges any additional filesystem specifications from the agent's directive.

        Args:
            universal_id (str): The unique identifier for the agent.
            file_spec (list): A list of file/folder specifications for the agent.
            agent_directive (dict, optional): The agent's directive, which may
                                              contain additional 'folders' or 'files'
                                              to create. Defaults to None.

        Returns:
            str: The absolute path to the agent's base communication directory.
        """
        base = ""
        validate_agent_ids((universal_id,))
        try:
            base = os.path.join(self.pm.resolve("runtime_comm"), universal_id)

            fsb = FileSystemBuilder()
            with runtime_directory(self.pm.base, self.pm.universe, self.pm.reboot_uuid,
                                   "comm", child=universal_id, create_child=True) as directory_fd:
                fsb.process_selection_fd(directory_fd, self.default_comm_file_spec)
                if file_spec:
                    fsb.process_selection_fd(directory_fd, file_spec)
                if agent_directive:
                    fs_node = agent_directive if isinstance(agent_directive, dict) else {}
                    folders = fs_node.get("folders", [])
                    if folders:
                        fsb.process_selection_fd(directory_fd, folders)
                    files = fs_node.get("files", {})
                    for name, content in files.items():
                        item = {"name": name, "type": "f", "content": content}
                        fsb.process_item_fd(directory_fd, item)

            print('comm_channel creation: end')
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[ensure_comm_channel] Unhandled exception during spawn of {tb}: {e}")
            raise
        return base

    def create_runtime(self):
        """
        Creates a new, temporary runtime directory (pod) for an agent instance.

        Args:
            universal_id (str): The unique identifier of the agent for which to
                                create the runtime. (Note: This is unused, the
                                pod is globally unique).

        Returns:
            tuple: A tuple containing the new UUID for the pod and the absolute
                   path to the pod directory.
        """
        new_uuid = f"{str(uuid.uuid4())}"
        pod_path = os.path.join(self.pm.resolve("runtime_pod"), new_uuid)
        with runtime_directory(self.pm.base, self.pm.universe, self.pm.reboot_uuid,
                               "pod", child=new_uuid, create_child=True):
            pass
        return new_uuid, pod_path

    def destroy_runtime(self, uuid):
        """
        Deletes a runtime directory (pod) and all its contents.

        Args:
            uuid (str): The UUID of the runtime pod to destroy.

        Returns:
            bool: True if the directory was found and deleted, False otherwise.
        """
        target = os.path.join(self.pm.resolve("runtime_pod"), uuid)
        if os.path.exists(target):
            shutil.rmtree(target)
            print(f"[SPAWNER] Destroyed runtime pod: {uuid}")
            return True
        return False

    def get_boot_log(self, path):
        """
        Reads the boot.json file from a given pod path.

        Args:
            path (str): The path to the runtime pod directory.

        Returns:
            tuple: A tuple containing a boolean success flag and the JSON content
                   of the boot log as a dictionary, or None on failure.
        """
        boot_file_path = os.path.join(path, 'boot.json')
        try:
            with open(boot_file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
            return True, content
        except (FileNotFoundError, json.JSONDecodeError):
            return False, None

    def spawn_agent(self, universe, spawner, universal_id, agent_name, spawn_uuid, tree_node=None, defer_gate=False, require_ready=False):
        """
        The main method to spawn a new agent process.

        This method performs the following steps:
        1.  Sets up a logger for the agent.
        2.  Resolves the path to the agent's source code.
        3.  Verifies the source code's integrity using a hash if provided.
        4.  Prepares a secure payload with paths, args, and keys.
        5.  Builds an encrypted environment for the process using Ghost Vault.
        6.  Launches the agent as a detached subprocess.
        7.  Records the spawn event and boot information.

        Args:
            spawn_uuid (str): The unique ID for this specific spawn instance (pod ID).
            agent_name (str): The name of the agent to spawn.
            universal_id (str): The persistent, unique identifier for the agent.
            spawner (str): The universal_id of the agent performing the spawn.
            tree_node (dict, optional): The configuration node for this agent from
                                      the directive. Defaults to None.
            universe (str, optional): The ID of the universe or session this
                                       spawn belongs to. Defaults to None.

        Returns:
            tuple: A tuple containing the new process ID (int) and the command (list)
                   used to launch the agent.

        Raises:
            RuntimeError: If the agent source code cannot be found or if the
                          hash verification fails.
        """

        logger=None
        process = None
        gate_open = False
        pod_context = None
        pod_fd = None
        run_fd = None
        import_fd = None
        ready_read = None
        ready_write = None
        try:

            lang = tree_node.get("lang", "python") if tree_node else "python"
            ext_map = {
                "python": "py",
                "go": "go",
                "javascript": "js",
                "bash": "sh",
                "rust": "rs"
            }
            ext = ext_map.get(lang, "py")

            site_paths= self.pm.full_resolution(universal_id, spawn_uuid, lang=lang, ext=ext)
            with static_directory(self.pm.base, self.pm.universe, self.pm.reboot_uuid,
                                  "comm", child=universal_id, create_child=True) as comm_fd:
                with child_directory(comm_fd, "logs", create=True) as log_fd:
                    logger = Logger(site_paths["static_comm_resolved"], "logs", "agent.log", directory_fd=log_fd)

            if self._keychain.get("encryption_enabled"):
                logger.set_encryption_key(self._keychain["swarm_key"])

            # Keep the audit trail inside the universe-owned static tree.  A
            # least-privilege swarm account must never need write access to the
            # shared /matrix installation root.
            with static_directory(self.pm.base, self.pm.universe, self.pm.reboot_uuid) as static_fd:
                append_file_at(static_fd, "spawn.log", f"{datetime.now().isoformat()} :: {universal_id} → {agent_name}\n".encode())

            #ensure the runtime pod path is created
            spawn_path = site_paths["runtime_pod_resolved"]
            pod_context = runtime_directory(self.pm.base, self.pm.universe, self.pm.reboot_uuid,
                                            "pod", child=spawn_uuid, create_child=True)
            pod_fd = pod_context.__enter__()

            site_root_path = self.pm.resolve("site_root")
            source_path = self.pm.resolve("agent_resolved", lang=lang, agent_name=agent_name, ext=ext)

            # Agents put SITE_ROOT and AGENT_PATH on sys.path. Every directory
            # they can import from must therefore remain administrator-owned.
            for validator in (lambda: trusted_shared_core_root(site_root_path),
                              lambda: trusted_shared_agent_root(site_root_path, lang)):
                tree = validator()
                if tree is None:
                    raise RuntimeError("Administrator-controlled source tree is missing")
                os.close(tree)
            import_fd = trusted_agent_import_root(site_root_path, lang, agent_name)

            # Integrity Check: Use embedded source or load from file and verify hash
            if tree_node and "src_embed" in tree_node:
                src_bytes = base64.b64decode(tree_node["src_embed"])
                logger.log(f"[SPAWN] Using embedded agent source for {agent_name}.")
            else:
                src_bytes = read_agent_source(site_root_path, lang, agent_name, ext)
                logger.log(f"[SPAWN] ✅ Found source for {agent_name} at {source_path}")

            real_hash = hashlib.sha256(src_bytes).hexdigest()
            expected_hash = tree_node.get("hash_bang") if tree_node else None

            #INTEGRITY DETECTION
            if expected_hash:
                if real_hash != expected_hash:
                    msg = (
                        f"HASH MISMATCH for agent '{agent_name}'\n"
                        f"  Source: {spawn_path}\n"
                        f"  Expected: {expected_hash}\n"
                        f"  Got:      {real_hash}\n"
                        f"  (Prefix: expected {expected_hash[:8]}... got {real_hash[:8]}...)\n"
                        "Aborting spawn."
                    )
                    logger.log(f"[SPAWN-FAIL] {msg}")
                    raise RuntimeError(f"Agent source hash mismatch:\n{msg}")
                else:
                    msg = (
                        f"HASH OK for agent '{agent_name}'\n"
                        f"  Source: {source_path}\n"
                        f"  hash_bang: {expected_hash}\n"
                        f"  Passed:    {real_hash[:12]}... (matched)"
                    )
                    logger.log(f"[SPAWN-HASH] {msg}")
            elif not expected_hash:
                logger.log(f"[SPAWN-HASH] No hash_bang provided for agent '{agent_name}' — spawn continues without integrity check.")

            # Write the verified source to a runnable file in the pod
            run_path = os.path.join(spawn_path, "run")
            vault_path = os.path.join(spawn_path, "vault")
            src_bytes.decode("utf-8")  # fail before publishing non-Python source
            write_file_at(pod_fd, "run", src_bytes, mode=0o600)
            # Executing a regular file descriptor does not prevent in-place
            # rewrites. A sealed memfd fixes the exact bytes verified above.
            if not sys.platform.startswith("linux") or not hasattr(os, "memfd_create"):
                raise RuntimeError("Sealed agent execution requires Linux memfd support")
            run_fd = os.memfd_create("matrix-agent", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            view = memoryview(src_bytes)
            while view:
                count = os.write(run_fd, view)
                if count <= 0:
                    raise OSError("Failed writing sealed agent source")
                view = view[count:]
            os.lseek(run_fd, 0, os.SEEK_SET)
            # Linux UAPI constants may be absent from Python's fcntl module.
            seals = 0x0008 | 0x0004 | 0x0002 | 0x0001
            fcntl.fcntl(run_fd, getattr(fcntl, "F_ADD_SEALS", 1033), seals)
            if fcntl.fcntl(run_fd, getattr(fcntl, "F_GET_SEALS", 1034)) & seals != seals:
                raise RuntimeError("Failed to seal agent source")
            with os.fdopen(os.dup(run_fd), "rb") as sealed:
                if hashlib.sha256(sealed.read()).hexdigest() != real_hash:
                    raise RuntimeError("Sealed agent source failed integrity verification")
            os.lseek(run_fd, 0, os.SEEK_SET)

            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            logger.log(f"[SPAWN-MGR] Spawning: {universal_id} ({agent_name})")
            print(f"[SPAWN-MGR] Spawning: {universal_id} ({agent_name})")

            # --- Prepare Secure Payload and Environment ---
            payload = {
                "path_resolution": {
                    "root_path": site_root_path,
                    "pod_path": site_paths["runtime_pod"],
                    "comm_path":  site_paths["runtime_comm"],
                    "static_comm_path": self.pm.resolve("static_comm"),
                    "static_comm_path_resolved": site_paths["static_comm_resolved"],
                    "reboot_uuid": self.pm.resolve("reboot_uuid"),
                    "agent_path": self.pm.resolve("agent"),
                    "incoming_path_template": os.path.join(site_paths["runtime_comm"], "$universal_id", "incoming"),
                    "comm_path_resolved": site_paths["runtime_comm_resolved"],
                    "pod_path_resolved": site_paths["runtime_pod_resolved"],
                    "poke_worker_file": os.path.join(site_paths["runtime_comm"], universal_id, "hello.moto", "poke.worker"),
                    "site_root_path": site_root_path,
                    "install_path": site_root_path,
                    # path of .matrixswarm dir - where session agent, boot_directive, and certs live
                    "python_site": self.python_site,
                    "python_exec": self.python_exec or "python3"
                },
                "args": {
                    "install_name": spawn_uuid,
                    "matrix": self.matrix_universal_id,
                    "spawner": spawner,
                    "universal_id": universal_id,
                    "agent_name": agent_name,
                    "universe": universe,
                    "site_root_path": site_root_path,
                    "verbose": int(self.verbose),
                    "debug": int(self.debug),
                    "rug_pull": int(self.rug_pull),
                    "protect_memory": int(self.protect_memory),
                },
                "tree_node": tree_node,
                "source_sha256": real_hash,
                "secure_keys": {
                    "pub": self._keychain["pub"],
                    "priv": self._keychain["priv"]
                },
                "swarm_key": self._keychain["swarm_key"],
                "private_key": self._keychain["private_key"],
                "matrix_pub": self._keychain["matrix_pub"],
                "matrix_priv": self._keychain["matrix_priv"],
                "security_box": self._keychain["security_box"],
                "encryption_enabled": self._keychain["encryption_enabled"],
            }

            def sanitize_for_json(obj):
                if isinstance(obj, dict):
                    return {k: sanitize_for_json(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [sanitize_for_json(i) for i in obj]
                elif isinstance(obj, Path):
                    return str(obj)
                else:
                    return obj

            payload = sanitize_for_json(payload)
            env = build_encrypted_spawn_env(payload, vault_path, output_dir_fd=pod_fd)


            env.update({
                "SITE_ROOT": site_root_path,
                "AGENT_PATH": self.pm.resolve("agent"),
                "PYTHON_SITE": self.python_site,
                "PYTHONPATH": os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            })
            env["MATRIX_AGENT_RUN_FD"] = str(run_fd)
            if import_fd is not None:
                env["MATRIX_AGENT_IMPORT_FD"] = str(import_fd)
            if self.lifecycle_generation:
                env[GENERATION_ENV] = self.lifecycle_generation

            # --- Launch Process ---
            python_exec = self.python_exec or "python3"
            if self.protect_memory:
                if not sys.platform.startswith("linux"):
                    raise RuntimeError(
                        "Root-only agent memory protection requires Linux prctl"
                    )
                # The boundary must be applied after Python's exec transition.
                # A fixed, non-secret launcher keeps implementation source and
                # the agent run path out of the public process command line.
                env["MATRIX_AGENT_RUN_PATH"] = run_path
                protected_launcher = os.path.join(
                    site_root_path, "core", "python_core", "protected_launcher.py"
                )
                cmd = [
                    python_exec,
                    protected_launcher,
                    "--job",
                    f"{universe}:{universal_id}",
                ]
            else:
                fd_launcher = os.path.join(site_root_path, "core", "python_core", "fd_launcher.py")
                cmd = [python_exec, fd_launcher, "--job", f"{universe}:{universal_id}"]
            # Keep the child inert until its identity has been published. If
            # this process dies, the pipe closes and the launcher exits.
            env["MATRIX_GATED_COMMAND"] = json.dumps(cmd)
            env["MATRIX_AGENT_RUN_PATH"] = run_path
            gate_launcher = os.path.join(site_root_path, "core", "python_core", "gated_launcher.py")
            gate_cmd = [python_exec, gate_launcher, "--job", f"{universe}:{universal_id}"]
            if require_ready:
                ready_read, ready_write = os.pipe2(os.O_CLOEXEC)
                env["MATRIX_BOOT_READY_FD"] = str(ready_write)
            kwargs = {"preexec_fn": os.setsid} if os.name == "posix" else {}
            process = subprocess.Popen(
                gate_cmd,
                stdout=subprocess.DEVNULL if not self.verbose else None,
                stderr=subprocess.DEVNULL if not self.verbose else None,
                stdin=subprocess.PIPE,
                env=env,
                pass_fds=(pod_fd, run_fd) + ((import_fd,) if import_fd is not None else ()) + ((ready_write,) if ready_write is not None else ()),
                **kwargs
            )
            if ready_write is not None:
                os.close(ready_write)
                ready_write = None
            try:
                process_started_at = psutil.Process(process.pid).create_time()
            except (psutil.Error, OSError):
                process_started_at = None

            # --- Record Keeping ---
            spawn_record = {
                "uuid": spawn_uuid, "universal_id": universal_id, "agent_name": agent_name,
                "parent": spawner, "timestamp": timestamp, "pid": process.pid
            }
            with runtime_directory(self.pm.base, self.pm.universe, self.pm.reboot_uuid,
                                   "comm", child=universal_id) as comm_fd:
                with child_directory(comm_fd, "spawn", create=True) as spawn_fd:
                    write_file_at(spawn_fd, f"{timestamp}_{spawn_uuid}.spawn", json.dumps(spawn_record, indent=2).encode())
            boot_record = {"universal_id": universal_id, "boot_time": timestamp, "pid": process.pid,
                           "cmd": cmd, "source_sha256": real_hash}
            if process_started_at is not None:
                boot_record["process_started_at"] = process_started_at
            write_file_at(pod_fd, "boot.json", json.dumps(boot_record, indent=2).encode(), durable=True)

            if defer_gate:
                self._pending_gate = process
            else:
                process.stdin.write(b"1")
                process.stdin.flush()
                process.stdin.close()
            gate_open = True
            if ready_read is not None:
                self._ready_fd = ready_read
                ready_read = None

            logger.log(f"[SPAWN-LOG] Spawn recorded for PID {process.pid}")

        except Exception as e:
            if process is not None and not gate_open:
                if process.stdin is not None:
                    process.stdin.close()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise RuntimeError(f"[SPAWN-FAIL] Unhandled exception during spawn of {agent_name}: {e}")
        finally:
            if ready_read is not None:
                os.close(ready_read)
            if ready_write is not None:
                os.close(ready_write)
            if logger is not None:
                logger.close()
            if run_fd is not None:
                os.close(run_fd)
            if import_fd is not None:
                os.close(import_fd)
            if pod_fd is not None:
                pod_context.__exit__(None, None, None)

        return process.pid, cmd

    def release_pending_gate(self):
        process = self._pending_gate
        try:
            process.stdin.write(b"1")
            process.stdin.flush()
        finally:
            process.stdin.close()
            self._pending_gate = None

    def wait_until_ready(self, timeout=30):
        fd, self._ready_fd = self._ready_fd, None
        try:
            readable, _, _ = select.select([fd], [], [], timeout)
            if not readable or os.read(fd, 1) != b"1":
                raise RuntimeError("Matrix did not report successful startup")
        finally:
            os.close(fd)

    def close_ready_pipe(self):
        fd = getattr(self, "_ready_fd", None)
        if fd is not None:
            self._ready_fd = None
            os.close(fd)
