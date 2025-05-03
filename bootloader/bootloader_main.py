import traceback
import re
from pathlib import Path
from agent.core.class_lib.boot.config_loader import ConfigLoader
from agent.core.path_manager import PathManager
from agent.core.swarm_session_root import SwarmSessionRoot
from agent.core.core_spawner import CoreSpawner
from agent.core.class_lib.processes.reaper import Reaper
from agent.core.tree_parser import TreeParser

import os
from dotenv import load_dotenv

# Load the .env file
load_dotenv()


class BootloaderManager:
    def __init__(
            self,
            supported_universe=None,
            pod_root=None,
            comm_root=None,
            base_universe_path=None
    ):
        self.supported_universe = supported_universe
        self.pod_root = pod_root
        self.comm_root = comm_root
        self.base_universe_path = base_universe_path
        """
        Initialize the BootloaderManager with universe and communication paths.

        Args:
            base_universe_path (str): The base path for the universe (e.g., `/matrix/bb`).
            comm_root (str): Communication root path.
        """
        self.base_universe_path = base_universe_path  # Fixed at `/matrix/bb`
        self.comm_root = comm_root
        self.default_universe = "/matrix/bb"
        self.current_universe = None
        self.supported_universe = supported_universe or "bb"
        self.matrix_directive = None
        # Dynamically detect or set the boot folder
        self.current_boot = self.get_latest_boot_folder()
        if not self.current_boot:
            raise FileNotFoundError(f"No valid boot folder found in {base_universe_path}.")

        # Construct pod_root and boot_directive_path
        self.pod_root = os.path.join(self.base_universe_path, self.current_boot, "pod")
        self.boot_directive_path = os.path.abspath(os.path.join(os.getcwd(), "boot_directives"))

        # Debugging Output
        print(f"[DEBUG] Base Universe Path: {self.base_universe_path}")
        print(f"[DEBUG] Current Boot Folder: {self.current_boot}")
        print(f"[DEBUG] Pod Root: {self.pod_root}")
        print(f"[DEBUG] Boot Directive Path: {self.boot_directive_path}")

    def hardboot_existing_sessions(universe_id="bb", base_path="/matrix", timeout=10, logger=None):
        """
        Perform a hardboot for a universe by cleaning up previous session instances and processes.

        Args:
            universe_id (str): Universe to hardboot (e.g., "bb").
            base_path (str): Base matrix directory, typically '/matrix'.
            timeout (int): Timeout in seconds for graceful cleanup of agents. Default is 10.
            logger: Logger for structured logging (optional).
        """
        # Validate universe path
        universe_path = os.path.join(base_path, universe_id)
        if not os.path.exists(universe_path):
            raise FileNotFoundError(f"Universe path '{universe_path}' does not exist.")

        # Step 1: Locate Existing Boot Instances
        existing_sessions = []
        for item in os.listdir(universe_path):
            session_path = os.path.join(universe_path, item)
            if os.path.isdir(session_path):
                pod_path = os.path.join(session_path, "pod")
                comm_path = os.path.join(session_path, "comm")
                if os.path.exists(pod_path) and os.path.exists(comm_path):
                    existing_sessions.append({
                        "boot_id": item,
                        "pod_path": pod_path,
                        "comm_path": comm_path
                    })

        if logger:
            logger.log(f"[HARDBOOT] Found {len(existing_sessions)} existing sessions under '{universe_path}'.")
        else:
            print(f"Found {len(existing_sessions)} existing sessions under '{universe_path}'.")

        # Step 2: Use Reaper to Clean Up Existing Sessions
        for session in existing_sessions:
            boot_id = session["boot_id"]
            pod_path = session["pod_path"]
            comm_path = session["comm_path"]

            if logger:
                logger.log(f"[HARDBOOT] Cleaning up session '{boot_id}' with paths:")
                logger.log(f" > Pod Path: {pod_path}")
                logger.log(f" > Comm Path: {comm_path}")
            else:
                print(f"Cleaning up session '{boot_id}': pod_path='{pod_path}', comm_path='{comm_path}'.")

            # Initialize Reaper for the session
            reaper = Reaper(pod_root=pod_path, comm_root=comm_path, logger=logger, timeout=timeout)

            # Reap active jobs
            jobs_to_reap = reaper.find_bigbang_agents(f"--job {universe_id}")
            if jobs_to_reap:
                if logger:
                    logger.log(f"[HARDBOOT] Found {len(jobs_to_reap)} jobs in session '{boot_id}': {jobs_to_reap}")
                    logger.log("[HARDBOOT] Reaping jobs...")
                else:
                    print(f"Found {len(jobs_to_reap)} jobs in session '{boot_id}': {jobs_to_reap}. Reaping...")

                reaper.reap_all()
                reaper.wait_for_agents_shutdown()

                if logger:
                    logger.log(f"[HARDBOOT] All jobs in session '{boot_id}' have been terminated.")
                else:
                    print(f"All jobs in session '{boot_id}' have been terminated.")
            else:
                if logger:
                    logger.log(f"[HARDBOOT] No active jobs found in session '{boot_id}'.")
                else:
                    print(f"No active jobs found in session '{boot_id}'.")

            # Step 3: Remove the session paths
            if logger:
                logger.log(f"[HARDBOOT] Removing paths for session '{boot_id}'.")
            else:
                print(f"Removing paths for session '{boot_id}'.")

            os.system(f"rm -rf {pod_path}")
            os.system(f"rm -rf {comm_path}")

        # Step 4: Completion
        if logger:
            logger.log(f"[HARDBOOT] Cleanup for all existing sessions under universe '{universe_id}' completed.")
        else:
            print(f"Cleanup for all existing sessions under universe '{universe_id}' completed.")

    def hardboot_with_session(universe="bb", timeout=10):
        """
        Performs a hardboot for the specified universe using SwarmSessionRoot and Reaper.

        Args:
            universe (str): The universe name for which the hardboot is being performed. Default is "bb".
            timeout (int): Timeout for agents to shut down gracefully. Default is 10 seconds.
        """
        # Step 1: Initialize SwarmSessionRoot
        session = SwarmSessionRoot()

        # Extract session paths and logger
        paths = session.get_paths()
        comm_path = paths["comm_path"]
        pod_path = paths["pod_path"]
        logger = paths["logger"]  # Logger integrated from SwarmSessionRoot
        universe_id = paths["universe_id"]  # Ensure we always use the session's universe_id

        logger.log(f"[HARDBOOT] Starting hardboot for universe: {universe_id}")

        # Step 2: Initialize Reaper for Cleanup
        reaper = Reaper(
            pod_root=pod_path,
            comm_root=comm_path,
            logger=logger,
            timeout=timeout
        )
        logger.log(f"[HARDBOOT] Reaper initialized for universe: {universe_id}")

        # Step 3: Search for Active Jobs and Reap Them
        jobs_to_reap = reaper.find_bigbang_agents(f"--job {universe_id}")
        if jobs_to_reap:
            logger.log(
                f"[HARDBOOT] Found {len(jobs_to_reap)} active jobs: {jobs_to_reap}. Reaping all jobs..."
            )
            # Reap all identified jobs
            reaper.reap_all()

            # Wait for graceful shutdown
            reaper.wait_for_agents_shutdown()
            logger.log("[HARDBOOT] All active jobs have been gracefully terminated.")
        else:
            logger.log(f"[HARDBOOT] No active jobs found for universe: {universe_id}")

        # Step 4: Reset Runtime Directories
        logger.log(f"[HARDBOOT] Resetting runtime directories: pod_path='{pod_path}', comm_path='{comm_path}'")
        os.system(f"rm -rf {pod_path}")
        os.system(f"rm -rf {comm_path}")
        os.makedirs(pod_path, exist_ok=True)
        os.makedirs(comm_path, exist_ok=True)

        logger.log("[HARDBOOT] Runtime directories have been reset successfully.")

        # Step 5: Completion
        logger.log(f"[HARDBOOT] Hardboot for universe '{universe_id}' completed successfully.")

    def get_latest_boot_folder(self):
        """
        Locate the latest boot folder in the base universe path.

        Returns:
            str: The name of the latest boot folder, or None if no valid folder is found.
        """
        try:
            # List all items in the base_universe_path directory
            boot_folders = [
                d for d in os.listdir(self.base_universe_path)
                if os.path.isdir(os.path.join(self.base_universe_path, d))
            ]

            # Sort boot folders by name (assuming YYYYMMDD_HHMMSS format)
            boot_folders.sort(reverse=True)  # Most recent boot folder first

            # Return the latest valid folder name
            return boot_folders[0] if boot_folders else None

        except FileNotFoundError:
            print(f"[ERROR] Base universe path not found: {self.base_universe_path}")
            return None

        except Exception as e:
            print(f"[ERROR] An error occurred while finding the latest boot folder: {e}")
            return None


    def select_config(self):
        """
        Allow the user to select and load an entire configuration file.
        """
        print("==================================================")
        print("               CONFIGURATION SELECTION")
        print("==================================================")

        # Validate configuration directory
        if not os.path.exists(self.boot_directive_path):
            print(f"Error: Configuration directory not found: {self.boot_directive_path}")
            return

        # List available files in the boot directive directory
        config_files = [
            f for f in os.listdir(self.boot_directive_path)
            if f.endswith(".py") and not f.startswith("__")
        ]

        if not config_files:
            print("No configuration files found in:", self.boot_directive_path)
            return

        # Display menu of configurations
        for idx, file_name in enumerate(config_files, start=1):
            print(f"{idx}. {os.path.splitext(file_name)[0]}")  # Show file names without extensions

        print("==================================================")

        try:
            # Get user input
            choice = int(input("Enter the number corresponding to your configuration: ").strip())

            if choice < 1 or choice > len(config_files):
                print("Invalid selection. Please try again.")
                return

            # Map user selection to the appropriate file
            selected_file = config_files[choice - 1]
            selected_path = os.path.join(self.boot_directive_path, selected_file)

            # Load the selected configuration
            print(f"Loading configuration: {selected_file}")
            self.matrix_directive = ConfigLoader.load_configuration(selected_path)
            print("Configuration successfully loaded!")
            print(f"Loaded matrix_directive: {self.matrix_directive}")  # Debugging step

        except ValueError:
            print("Error: Input must be a number.")
        except Exception as e:
            print(f"[ERROR] Exception occurred: {e}")
            traceback.print_exc()

    def hard_reset_universe(self, MATRIX_UUID, BOOTLOADER_UUID):

        # RAZE THE UNIVERSE BEFORE REDEPLOYMENT
        universe_base_path = os.path.join("/matrix", self.supported_universe)
        current_boot_folder = os.path.basename(self.current_universe.strip("/"))

        for boot_id in os.listdir(universe_base_path):
            if boot_id == "latest" or boot_id == current_boot_folder:
                continue  # Skip latest and the current boot folder

            session_path = os.path.join(universe_base_path, boot_id)
            pod_path = os.path.join(session_path, "pod")
            comm_path = os.path.join(session_path, "comm")

            if not (os.path.isdir(pod_path) and os.path.isdir(comm_path)):
                continue

            print(f"[SWARMPURGE] Reaping stray agents in stale boot: {boot_id}")


            reaper = Reaper(pod_root=pod_path, comm_root=comm_path)
            found = reaper.find_bigbang_agents(pod_path)
            if found:
                print(f"[SWARMPURGE] {len(found)} agents found. Initiating purge...")
                reaper.reap_all()

        if not self.current_universe:
            print("No universe initialized. Call `initialize_universe()` first.")
            return

        if not self.matrix_directive:
            print("No configuration selected. Call `select_config()` first.")
            return

        universe_root = self.current_universe.strip("/")
        pod_path = os.path.join("/", universe_root, "pod")
        comm_path = os.path.join("/", universe_root, "comm")

        os.makedirs(pod_path, exist_ok=True)
        os.makedirs(comm_path, exist_ok=True)

    def get_available_boots(self):
        """
        Get a list of available boots in the pod directory.
        :return: List of directories in the pod root that are valid boots.
        """
        return [str(path) for path in Path(self.pod_root).iterdir() if path.is_dir()]

    def show_available_boots(self):
        """
        Display the available boots and indicate which one is active.
        """
        print("==================================================")
        print("              AVAILABLE BOOTS")
        print("==================================================")
        boots = self.get_available_boots()
        if not boots:
            print("No boots available.")
        for i, boot in enumerate(boots, start=1):
            status = "[ACTIVE]" if boot == self.active_boot_path else "[INACTIVE]"
            print(f"{i}. {boot} {status}")
        print("==================================================")

    def terminate_active_boots(self, skip_path):
        """
        Terminate all running boots except the one specified by skip_path.
        :param skip_path: Path to the boot that should not be terminated.
        """
        for boot in self.get_available_boots():
            if boot == skip_path:
                continue
            print(f"Terminating boot: {boot}")
            # Use the Reaper to clean up all processes for the specified boot
            reaper = Reaper(pod_root=Path(boot), comm_root=self.comm_root)
            reaper.reap_all()

    def boot_selected_directory(self, selected_boot_path, matrix_directive, MATRIX_UUID, BOOTLOADER_UUID):
        """
        Initialize and set the active boot for the selected directory.
        :param selected_boot_path: Path of the boot to activate.
        :param matrix_directive: Boot-specific configuration directive.
        :param MATRIX_UUID: UUID for the current matrix session.
        :param BOOTLOADER_UUID: UUID for this bootloader instance.
        """
        self.terminate_active_boots(selected_boot_path)  # Clean up other boots

        pm = PathManager(base_path=os.path.join("/", self.universe_root))
        cp = CoreSpawner(path_manager=pm)  # Assumes CoreSpawner is correctly imported
        cp.reset_hard()  # Reset the system state
        tp = TreeParser({})  # Initialize the TreeParser, if needed
        comm_file_spec = [
            {'name': 'agent_tree_master.json', 'type': 'f', 'atomic': True, 'content': tp.load_dict(matrix_directive)},
            {'name': 'hello.moto', 'type': 'd'},
            {'name': 'incoming', 'type': 'd'},
            {'name': 'payload', 'type': 'd'},
        ]  # Define comm file specifications if required

        # Ensure the communication channel and spawn runtime
        cp.ensure_comm_channel(MATRIX_UUID, comm_file_spec, matrix_directive)
        new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
        cp.spawn_agent(new_uuid, MATRIX_UUID, MATRIX_UUID, BOOTLOADER_UUID, matrix_directive)

        # Update the active boot path
        self.active_boot_path = selected_boot_path
        print(f"Boot {selected_boot_path} is now active.")

    def main_menu(self):
        while True:
            print("==================================================")
            print("             BOOTLOADER CONTROL SCREEN")
            print("==================================================")
            print("Please choose an option:")
            print("1. Initialize/Select Universe")
            print("2. Select Configuration")
            print("3. Perform Hard Reset with Selected Config")
            print("4. Exit")
            print("==================================================")
            choice = input("Your choice: ")

            if choice == "1":
                self.initialize_universe()
            elif choice == "2":
                self.select_config()
            elif choice == "3":

                if not self.current_universe:
                    print("Error: No universe initialized! Run Step 1.")
                elif not self.matrix_directive:
                    print("Error: No configuration selected! Run Step 2.")
                else:
                    self.deploy_matrix()

            elif choice == "4":
                print("Exiting...")
                break
            else:
                print("Invalid choice. Please try again.")

    def deploy_matrix(self, MATRIX_UUID="matrix", BOOTLOADER_UUID="bootloader"):

        if not self.current_universe or not self.universe_root_path:
            print("[ERROR] Bootloader is not initialized. Please run Step 1 (Initialize Universe).")
            return

        if not self.current_universe:
            print("Error: No universe initialized!")
            return
        if not self.matrix_directive:
            print("Error: No configuration selected!")
            return

        universe_base_path = self.universe_root_path
        current_boot_folder = os.path.basename(self.current_universe.strip("/"))

        for boot_id in os.listdir(universe_base_path):
            if boot_id == "latest" or boot_id == current_boot_folder:
                continue
            session_path = os.path.join(universe_base_path, boot_id)
            pod_path = os.path.join(session_path, "pod")
            comm_path = os.path.join(session_path, "comm")

            if os.path.isdir(pod_path) and os.path.isdir(comm_path):
                print(f"[SWARMPURGE] Reaping stale boot: {boot_id}")
                reaper = Reaper(pod_root=pod_path, comm_root=comm_path)
                reaper.reap_all()

        universe_path = self.current_universe.strip("/").split("/")
        universe_id = universe_path[1] if len(universe_path) > 1 else "bb"

        matrix_directive = self.matrix_directive

        if not self.matrix_directive:
            print("[ERROR] matrix_directive is None — did you load a config?")
            return

        matrix_without_children = {
            k: v for k, v in matrix_directive.items() if k != "children"
        }

        tp = TreeParser({})
        comm_file_spec = [
            {
                'name': 'agent_tree_master.json',
                'type': 'f',
                'atomic': True,
                'content': tp.load_dict(matrix_directive)
            },
            {'name': 'hello.moto', 'type': 'd'},
            {'name': 'incoming', 'type': 'd'},
            {'name': 'payload', 'type': 'd'}
        ]

        if not all([MATRIX_UUID, BOOTLOADER_UUID, self.universe_root_path]):
            print(f"[DEBUG] MATRIX_UUID: {MATRIX_UUID}")
            print(f"[DEBUG] BOOTLOADER_UUID: {BOOTLOADER_UUID}")
            print(f"[DEBUG] universe_root_path: {self.universe_root_path}")
            print("[ERROR] One or more required paths are missing.")
            return

        site_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        pm = PathManager(
            root_path=os.path.join(self.universe_root_path, "latest"),
            agent_override=os.path.join(site_root, "agent"),
        )

        cp = CoreSpawner(path_manager=pm)


        cp.ensure_comm_channel(MATRIX_UUID, comm_file_spec, matrix_directive)
        new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
        cp.spawn_agent(new_uuid, MATRIX_UUID, MATRIX_UUID, BOOTLOADER_UUID, matrix_without_children)

        print(f"[SPAWN-MANAGER] Matrix {MATRIX_UUID} deployed at: {pod_path}")

    def initialize_universe(self):
        print("==================================================")
        print("             UNIVERSE INITIALIZATION")
        print("==================================================")

        universe_root = input("Enter universe root path (default is /matrix): ").strip()
        if not universe_root:
            universe_root = "/matrix"

        while True:
            universe_name = input("Enter universe ID (e.g. bb, test, main): ").strip()
            if not universe_name:
                universe_name = "bb"
                break
            elif re.match(r'^[a-zA-Z0-9_-]+$', universe_name):
                break
            else:
                print("[ERROR] Invalid universe ID.")

        full_universe_path = os.path.join(universe_root, universe_name)
        os.environ["UNIVERSE_ID"] = universe_name

        session = SwarmSessionRoot()
        self.current_universe = session.base_path
        self.universe_root_path = full_universe_path
        print(f"Universe initialized to: {self.current_universe}")


    def hardboot_with_job_paths(universe_id="bb", base_path="/matrix", timeout=10, logger=None):
        """
        Perform a hardboot by identifying and cleaning up job processes tied to /matrix/<universe_id>/<boot_id>/pod.

        Args:
            universe_id (str): Universe to hardboot (e.g., "bb").
            base_path (str): Base matrix directory, typically `/matrix`.
            timeout (int): Timeout for graceful shutdown of active processes. Default is 10 seconds.
            logger: Logger for structured logging (optional).
        """
        # Step 1: Locate Universe Path
        universe_path = os.path.join(base_path, universe_id)
        if not os.path.exists(universe_path):
            raise FileNotFoundError(f"Universe path '{universe_path}' does not exist.")

        # Step 2: Find Active Boot Sessions
        existing_sessions = []
        for boot_id in os.listdir(universe_path):
            session_path = os.path.join(universe_path, boot_id)
            pod_path = os.path.join(session_path, "pod")
            comm_path = os.path.join(session_path, "comm")

            if os.path.isdir(session_path) and os.path.exists(pod_path):
                # Look for job-specific subdirectories in pod_path
                job_dirs = [
                    os.path.join(pod_path, name)
                    for name in os.listdir(pod_path)
                    if os.path.isdir(os.path.join(pod_path, name))
                ]
                existing_sessions.append({
                    "boot_id": boot_id,
                    "pod_path": pod_path,
                    "comm_path": comm_path,
                    "job_dirs": job_dirs
                })

        if logger:
            logger.log(f"[HARDBOOT] Found {len(existing_sessions)} sessions in '{universe_path}' to clean.")
        else:
            print(f"Found {len(existing_sessions)} sessions in '{universe_path}' to clean.")

        # Step 3: Reap Jobs and Cleanup `pod`
        for session in existing_sessions:
            boot_id = session["boot_id"]
            pod_path = session["pod_path"]
            comm_path = session["comm_path"]
            job_dirs = session["job_dirs"]

            if logger:
                logger.log(f"[HARDBOOT] Cleaning up session: {boot_id}")
                logger.log(f" > Pod Path: {pod_path}")
                logger.log(f" > Comm Path: {comm_path}")
            else:
                print(f"Cleaning up session: {boot_id}")
                print(f" > Pod Path: {pod_path}")
                print(f" > Comm Path: {comm_path}")

            # Initialize Reaper for this session
            reaper = Reaper(pod_root=pod_path, comm_root=comm_path, logger=logger, timeout=timeout)

            # Reap jobs tied to the pod path
            jobs_to_reap = []
            for job_dir in job_dirs:
                # The specific `run` file in this directory would have processes tied to it
                run_file = os.path.join(job_dir, "run")
                if os.path.exists(run_file):
                    jobs_to_reap.extend(reaper.find_bigbang_agents(run_file))

            if jobs_to_reap:
                if logger:
                    logger.log(
                        f"[HARDBOOT] Found {len(jobs_to_reap)} jobs tied to boot session '{boot_id}': {jobs_to_reap}"
                    )
                    logger.log(f"[HARDBOOT] Reaping jobs for session '{boot_id}'...")
                else:
                    print(
                        f"Found {len(jobs_to_reap)} jobs tied to boot session '{boot_id}': {jobs_to_reap}. Reaping..."
                    )

                reaper.reap_all()
                reaper.wait_for_agents_shutdown()

                if logger:
                    logger.log(f"[HARDBOOT] All jobs for session '{boot_id}' have been terminated.")
                else:
                    print(f"All jobs for session '{boot_id}' have been terminated.")
            else:
                if logger:
                    logger.log(f"[HARDBOOT] No active jobs found in session '{boot_id}'.")
                else:
                    print(f"No active jobs found in session '{boot_id}'.")

            # Step 4: Remove Runtime Paths
            if logger:
                logger.log(f"[HARDBOOT] Removing paths for session '{boot_id}'...")
            else:
                print(f"Removing paths for session '{boot_id}'.")

            os.system(f"rm -rf {pod_path}")
            os.system(f"rm -rf {comm_path}")

        # Step 5: Completion
        if logger:
            logger.log(f"[HARDBOOT] Cleanup for all sessions in universe '{universe_id}' completed.")
        else:
            print(f"Cleanup for all sessions in universe '{universe_id}' completed.")

    def spawn_manager(self, universe_id="bb", MATRIX_UUID="matrix", BOOTLOADER_UUID="bootloader"):

        pm = PathManager(root_path=os.path.join(self.universe_root_path, "latest"))

        # 1. Kill any living agents in the current pod/comm before nuking
        reaper = Reaper(
            pod_root=pm.get_path("pod", trailing_slash=False),
            comm_root=pm.get_path("comm", trailing_slash=False)
        )
        reaper.reap_all()

        # 2. Hard reset the pod and comm
        cp = CoreSpawner(path_manager=pm)
        cp.reset_hard()

        matrix_directive = self.matrix_directive

        # 3. Build comm structure from tree
        tp = TreeParser({})
        comm_file_spec = [
            {
                'name': 'agent_tree_master.json',
                'type': 'f',
                'atomic': True,
                'content': tp.load_dict(matrix_directive)
            },
            {'name': 'hello.moto', 'type': 'd'},
            {'name': 'incoming', 'type': 'd'},
            {'name': 'payload', 'type': 'd'}
        ]

        # 4. Remove children for the root Matrix spawn
        matrix_without_children = {
            k: v for k, v in matrix_directive.items() if k != "children"
        }

        # 5. Deploy Matrix
        cp.ensure_comm_channel(MATRIX_UUID, comm_file_spec, matrix_directive)
        new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
        cp.spawn_agent(new_uuid, MATRIX_UUID, MATRIX_UUID, BOOTLOADER_UUID, matrix_without_children)

        print(f"[SPAWN-MANAGER] Matrix {MATRIX_UUID} deployed at: {pod_path}")


if __name__ == "__main__":
    # No session! We're just managing boots.
    try:
        manager = BootloaderManager(
            supported_universe="bb",
            pod_root="/matrix/bb/latest/pod",
            comm_root="/matrix/bb/latest/comm",
            base_universe_path="/matrix/bb"
        )

        os.makedirs(manager.boot_directive_path, exist_ok=True)

        print(f"[INFO] Boot directive path is valid: {manager.boot_directive_path}")
        manager.main_menu()

    except FileNotFoundError as fnf_error:
        print(f"[ERROR] {fnf_error}")

    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")