"""
Authored by Daniel F MacDonald and ChatGPT aka The Generals
Gemini, doc-rocking the Swarm to perfection.

MatrixSwarm Boot Loader: Initializes and launches a MatrixSwarm universe.

This script is the primary entry point for deploying and managing MatrixSwarm environments.
It handles the initialization of new swarm workspaces, the booting of agent hierarchies based on
a specified directive, and the management of swarm pointers for seamless workspace switching.

The bootstrapper intelligently detects the Python environment to ensure that agents are
spawned with the correct interpreter and dependencies. It is designed to be run from the
command line and serves as the "ignition key" for the entire swarm.

Key Features:
- **Workspace Initialization**: Creates a new '.matrixswarm' workspace with the required
  directory structure (`agent/`, `boot_directives/`, `certs/`) using the `--init` flag.
- **Pointer System**: Manages a `.swarm` file that points to the active workspace,
  allowing operators to control different swarms from any directory. The `--switch`
  command updates this pointer.
- **Directive-Based Booting**: Launches a swarm configuration defined in a Python
  directive file from the `boot_directives/` directory.
- **Environment Detection**: Automatically finds the appropriate Python executable and
  site-packages directory to ensure agents run correctly. These can be overridden
  with `--python-bin` and `--python-site`.
- **Secure & Standard Boot**: Supports both encrypted and plaintext directives, with
  encryption on by default for secure operations.

Usage:
  # Initialize a new .matrixswarm workspace in the current directory
  python3 site_boot.py --init

  # Initialize a workspace in a specific location
  python3 site_boot.py --init --install-path /srv/matrixswarm/prod

  # Switch the current directory to control a different workspace
  python3 site_boot.py --switch /srv/matrixswarm/prod

  # Boot a swarm universe using a specific directive
  python3 site_boot.py --universe my_app --directive gatekeeper-demo

  # Boot with verbose output and debugging enabled
  python3 site_boot.py --universe my_app --directive test-01 --debug --verbose

  # Override the Python interpreter for agent execution
  python3 site_boot.py --universe my_app --python-bin /usr/bin/python3.9

Arguments:
    --universe (str): A unique ID for the swarm universe (e.g., "ai", "prod"). Required.
    --directive (str): The name of the directive file from `boot_directives/`
                       (without the .py extension). Defaults to "default".
    --init (flag): When set, initializes a new .matrixswarm workspace and creates a
                   `.swarm` pointer in the current directory.
    --install-path (str): Specifies the directory to install the new .matrixswarm
                          workspace. Used in conjunction with `--init`.
    --switch (str): Points the `.swarm` file in the current directory to a different
                    `.matrixswarm` workspace, making it the active target for commands.
    --matrix-path (str): Specifies a `.matrixswarm` workspace to use for a single boot
                         operation, overriding the `.swarm` pointer file.
    --reboot (flag): If set, performs a "soft" reboot by killing existing universe
                     processes before starting, instead of a full teardown.
    --python-site (str): Overrides the auto-detected Python site-packages path.
                         For advanced use cases.
    --python-bin (str): Overrides the auto-detected Python interpreter binary. For
                        advanced use cases.
    --encrypted-directive (str): Path to an AES-GCM encrypted directive file.
    --swarm_key (str): The Base64 encoded swarm key used to decrypt an encrypted
                       directive.
    --encryption-off (flag): Disables encryption for the boot session. Not recommended
                             for production environments.
    --debug (flag): Enables detailed debug logging for verbose diagnostic output.
    --verbose (flag): Enables verbose printouts in the console.
"""
import os
import shutil
import time
import argparse
import json
import base64
import sys
import subprocess
import site
import matrixswarm
from pathlib import Path

def get_active_matrixswarm_path(arg_path=None):
    if arg_path:
        active_path = Path(arg_path).expanduser().resolve()
    else:
        here = Path.cwd()
        venv_dir = here / ".venv"
        if venv_dir.exists():
            active_path = venv_dir.parent / ".matrixswarm"
        else:
            active_path = here / ".matrixswarm"
    return active_path

def matrixswarm_dirs_valid(base_path):
    """Checks that the core subdirs exist and returns True/False."""
    must_have = [
        base_path / "agent",
        base_path / "boot_directives",
        base_path / "certs" / "https_certs",
        base_path / "certs" / "socket_certs",
        base_path / ".matrix"
    ]
    return all(p.exists() for p in must_have)

def find_swarm_pointer(start_path=None):
    # 1. Look in CWD and parents (standard)
    path = Path(start_path or Path.cwd()).resolve()
    for parent in [path] + list(path.parents):
        swarm_file = parent / ".swarm"
        if swarm_file.exists():
            return swarm_file

    # 2. Fallback to global pointer
    global_swarm = Path.home() / ".matrixswarm_pointer"
    if global_swarm.exists():
        return global_swarm

    return None  # Not found

def load_matrix_config(base_path):
    config_path = base_path / ".matrix"
    with open(config_path) as f:
        return json.load(f)

def abort_boot(msg):
    print(f"[MatrixSwarm BOOT ABORTED]: {msg}")
    print("Please run --init to create a valid workspace, or specify the correct --matrix-path.")
    sys.exit(1)

SWARM_POINTER = ".swarm"

def write_swarm_pointer(install_path):
    cwd_pointer = Path.cwd() / ".swarm"
    global_pointer = Path.home() / ".matrixswarm_pointer"

    for path in [cwd_pointer, global_pointer]:
        with open(path, "w") as f:
            f.write(str(install_path))

    print(f"[SWARM] Pointer written to: {cwd_pointer} and {global_pointer}")

def find_matrixswarm_path(cli_path=None):
    # 1. CLI arg wins
    if cli_path:
        return Path(cli_path).expanduser().resolve()
    # 2. .swarm pointer in CWD
    swarm_pointer = Path.cwd() / SWARM_POINTER
    if swarm_pointer.exists():
        with open(swarm_pointer) as f:
            return Path(f.read().strip()).expanduser().resolve()
    # 3. Env var fallback
    env_path = os.environ.get("MATRIXSWARM_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    # 4. Fallback
    here = Path.cwd()
    venv_dir = here / ".venv"
    if venv_dir.exists():
        return venv_dir.parent / ".matrixswarm"
    else:
        return here / ".matrixswarm"

def create_user_dirs_and_copy_bases(install_path=None):
    # Determine install path
    if install_path is None:
        # Default: .matrixswarm in the parent dir of the venv or script
        here = Path.cwd()
        venv_dir = here / ".venv"
        if venv_dir.exists():
            install_path = venv_dir.parent / ".matrixswarm"
        else:
            install_path = here / ".matrixswarm"
    else:
        install_path = Path(install_path).expanduser().resolve()

    print(f"\n[MatrixSwarm INIT] Using install path: {install_path}")

    # Folders to create/copy
    boot_directives_src = Path(__file__).resolve().parent / "boot_directives"
    agent_src = Path(__file__).resolve().parent / "agent"

    agent_dst = install_path / "agent"
    boot_directive_dst = install_path / "boot_directives"
    certs_dst = install_path / "certs"
    https_certs_dst = certs_dst / "https_certs"
    socket_certs_dst = certs_dst / "socket_certs"
    env_src = Path(__file__).resolve().parent / "SAMPLE.env"

    install_path.mkdir(parents=True, exist_ok=True)
    agent_dst.mkdir(parents=True, exist_ok=True)
    boot_directive_dst.mkdir(parents=True, exist_ok=True)
    https_certs_dst.mkdir(parents=True, exist_ok=True)
    socket_certs_dst.mkdir(parents=True, exist_ok=True)

    if agent_src.exists():
        for item in agent_src.iterdir():
            dest = agent_dst / item.name
            if item.is_dir():
                if not dest.exists():
                    shutil.copytree(item, dest)
                    print(f"   Copied agent folder {item.name} → {agent_dst}")
                else:
                    print(f"   (Skipped agent folder {item.name}, already exists)")
            elif item.is_file():
                if not dest.exists():
                    shutil.copy(item, dest)
                    print(f"   Copied agent file {item.name} → {agent_dst}")
                else:
                    print(f"   (Skipped agent file {item.name}, already exists)")
    else:
        print(f"   (No agent/ to copy from in {agent_src})")

    # Copy all boot_directives folders and files
    if boot_directives_src.exists():
        for item in boot_directives_src.iterdir():
            dest = boot_directive_dst / item.name
            if item.is_dir():
                if not dest.exists():
                    shutil.copytree(item, dest)
                    print(f"   Copied boot_directive folder {item.name} → {boot_directive_dst}")
                else:
                    print(f"   (Skipped boot_directive folder {item.name}, already exists)")
            elif item.is_file():
                if not dest.exists():
                    shutil.copy(item, dest)
                    print(f"   Copied boot_directive file {item.name} → {boot_directive_dst}")
                else:
                    print(f"   (Skipped boot_directive file {item.name}, already exists)")
    else:
        print(f"   (No boot_directives/ to copy from in {boot_directives_src})")

    # Copy .env file for secrets/passwords
    env_dst = install_path / "SAMPLE.env"
    if env_src.exists() and not env_dst.exists():
        shutil.copy(env_src, env_dst)
        print(f"   Copied SAMPLE.env → {env_dst}")
    elif env_dst.exists():
        print(f"   (.env SAMPLE.already exists at {env_dst}, not overwritten)")
    else:
        print(f"   (No SAMPLE.env found to copy from {env_src})")

    # Create config file for tracking
    config = {
        "install_path": str(install_path),
        "agent": str(agent_dst),
        "boot_directives": str(boot_directive_dst),
        "certs": str(certs_dst),
        "https_certs": str(https_certs_dst),
        "socket_certs": str(socket_certs_dst),
        "env": str(env_dst)
    }
    config_path = install_path / ".matrix"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    #CERT TOOL COPY OVER
    cert_tool_src = Path(__file__).resolve().parent / "tools" / "generate_certs.sh"
    cert_tool_dst = install_path / "generate_certs.sh"

    if cert_tool_src.exists() and not cert_tool_dst.exists():
        shutil.copy(cert_tool_src, cert_tool_dst)
        os.chmod(cert_tool_dst, 0o755)
        print(f"   Copied generate_certs.sh → {cert_tool_dst}")
    else:
        print(f"   (Skipped generate_certs.sh, already exists or missing)")


    print(f"\n[MatrixSwarm INIT] Wrote directory map to {config_path}")

    print("\n[MatrixSwarm INIT] ✔ Done! All folders and config created.\n")


    write_swarm_pointer(install_path)

def main():

    # Path prep
    import os

    #if the directive is encrypted, decrypt
    def decrypt_directive(encrypted_path, swarm_key_b64):

        with open(encrypted_path, "r", encoding="utf-8") as f:
            bubble = json.load(f)

        key = base64.b64decode(swarm_key_b64)
        nonce = base64.b64decode(bubble["nonce"])
        tag = base64.b64decode(bubble["tag"])
        ciphertext = base64.b64decode(bubble["ciphertext"])

        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        decrypted = cipher.decrypt_and_verify(ciphertext, tag)
        return json.loads(decrypted.decode())

    try:

        PACKAGE_ROOT = os.path.dirname(matrixswarm.__file__)
    except ImportError:
        # fallback for source/dev runs
        PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "matrixswarm"))

    print(f"PACKAGE_ROOT: {PACKAGE_ROOT}")

    if PACKAGE_ROOT  not in sys.path:
        sys.path.insert(0, PACKAGE_ROOT )

    import hashlib
    from pathlib import Path
    from matrixswarm.core.mixin.ghost_vault import generate_agent_keypair
    from cryptography.hazmat.primitives import serialization
    from matrixswarm.core.core_spawner import CoreSpawner
    from matrixswarm.core.tree_parser import TreeParser
    from matrixswarm.core.class_lib.processes.reaper import Reaper
    from matrixswarm.core.path_manager import PathManager
    from matrixswarm.core.swarm_session_root import SwarmSessionRoot
    from matrixswarm.boot_directives.load_boot_directive import load_boot_directive
    from matrixswarm.core.utils.boot_guard import enforce_single_matrix_instance, validate_universe_id
    from matrixswarm.core.utils.crypto_utils import generate_aes_key
    from Crypto.Cipher import AES
    from Crypto.PublicKey import RSA

    from matrixswarm.core.class_lib.packet_delivery.packet.standard.general.json.packet import Packet
    from matrixswarm.core.class_lib.packet_delivery.delivery_agent.file.json_file.delivery_agent import DeliveryAgent
    from matrixswarm.core.class_lib.packet_delivery.utility.crypto_processors.packet_encryption_factory import packet_encryption_factory
    from matrixswarm.core.class_lib.packet_delivery.utility.crypto_processors.football import Football

    # === ARGUMENTS ===
    parser = argparse.ArgumentParser(description="MatrixSwarm Boot Loader", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--init", action="store_true", help="Initialize user directories and copy base files")
    parser.add_argument("--install-path", help="(For --init) Path to install .matrixswarm (default: alongside .venv)")
    parser.add_argument("--matrix-path", help="Use a different .matrixswarm location (default: alongside .venv)")
    parser.add_argument("--universe",  default="ai", help="Target universe ID (default: ai)")
    parser.add_argument("--directive", default="default", help="Boot directive (e.g., matrix)")
    parser.add_argument("--reboot", action="store_true", help="Soft reboot — skip hard cleanup")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose terminal output")
    parser.add_argument("--python-site", help="Override Python site-packages path to inject")
    parser.add_argument("--python-bin", help="Override Python interpreter to use for agent spawns")
    parser.add_argument("--encrypted-directive", help="Path to AES-GCM encrypted directive JSON")
    parser.add_argument("--swarm_key", help="Base64-encoded swarm key used to decrypt directive")
    parser.add_argument("--encryption-off", action="store_true", help="Turn encryption off for all agents")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--switch", help="Switch to a new .matrixswarm location and update .swarm pointer")
    parser.add_argument("--show-path", action="store_true", help="Print active .matrixswarm path and exit")

    args, unknown = parser.parse_known_args()

    # Special: handle --init instantly
    if args.init:

        current_dir = Path.cwd().resolve()
        if ".matrixswarm" in current_dir.parts and current_dir.name == ".matrixswarm":
            print("🚫 [INIT BLOCKED] You're currently inside an active .matrixswarm directory.")
            print("    Please run --init from the parent project folder or home directory.")
            sys.exit(1)

        create_user_dirs_and_copy_bases(args.install_path or args.matrix_path)
        print("User directories initialized. Exiting.")
        sys.exit(0)

    if args.switch:
        switch_path = Path(args.switch).expanduser().resolve()
        if not (switch_path / ".matrix").exists():
            print(f"[ERROR] The target .matrixswarm directory at {switch_path} does not contain a .matrix file!")
            print("You must provide a valid swarm workspace. Aborting.")
            sys.exit(1)
        # Write .swarm pointer in the current directory
        with open(".swarm", "w") as f:
            f.write(str(switch_path))
        print(f"[SWARM] Pointer file .swarm created/updated, now pointing to {switch_path}")
        print("[SWARM] You may now run matrixswarm-boot as normal from this directory.")
        sys.exit(0)

    swarm_pointer = find_swarm_pointer()
    if not swarm_pointer:
        print("Cannot find .swarm pointer anywhere up the directory tree.")
        sys.exit(1)
    with open(swarm_pointer) as f:
        matrix_path = Path(f.read().strip()).expanduser().resolve()

    if args.show_path:
        print(f"Active .matrixswarm path: {matrix_path}")
        sys.exit(0)

    if not (matrix_path / ".matrix").exists():
        print(f"[MatrixSwarm BOOT ABORTED]: Target path from .swarm ({matrix_path}) is missing .matrix.")
        print("This is not a valid MatrixSwarm workspace. Run --init to create one.")
        sys.exit(1)

    if not matrixswarm_dirs_valid(matrix_path):
        abort_boot(f"MatrixSwarm directory {matrix_path} is missing required folders/files.")

    config = load_matrix_config(matrix_path)

    #agents_dir = config["agents"]
    #directives_dir = config["directives"]
    #https_certs_dir = config["https_certs"]
    #socket_certs_dir = config["socket_certs"]
    #env_path = config["env"]

    universe_id = args.universe.strip()
    boot_name = args.directive.strip().replace(".py", "")
    reboot = args.reboot
    #show realtime log prints - be warned you will need to open another terminal to
    #terminate the swarm
    verbose = args.verbose
    #turns debugging on
    debug = args.debug

    encryption_enabled = not args.encryption_off


    # === ENVIRONMENT DETECTION ===
    def check_python_env(user_python_bin=None, user_site_path=None, required_module="discord"):
        # Step 1: Determine Python binary
        python_exec = user_python_bin if user_python_bin else sys.executable
        print(f"🔍 Using Python: {python_exec}")

        # Step 2: Check if required module is importable
        try:
            __import__(required_module)
            print(f"'{required_module}' is installed")
        except ImportError:
            print(f"'{required_module}' not found in this environment.")
            print("Attempting to install py-cord...")

            try:
                subprocess.check_call([python_exec, "-m", "pip", "install", "py-cord"])
                print(" py-cord installed successfully.")
            except subprocess.CalledProcessError:
                print(" Failed to install py-cord. Please install it manually.")
                sys.exit(1)

        # Step 3: Determine site-packages path
        if user_site_path:
            python_site = user_site_path
            print(f"[Override] site-packages: {python_site}")
        else:
            try:
                python_site = next(p for p in site.getsitepackages() if "site-packages" in p and Path(p).exists())
            except Exception:
                python_site = site.getusersitepackages()

        if not Path(python_site).exists():
            print(f"Detected site-packages path does not exist: {python_site}")
            sys.exit(1)

        print(f"Using site-packages path: {python_site}")

        return {
            "python_exec": python_exec,
            "python_site": python_site
        }

    env = check_python_env(
        user_python_bin=args.python_bin,
        user_site_path=args.python_site
    )

    python_exec = env["python_exec"]
    python_site = env["python_site"]
    if args.python_site:
        print(f"[Override] --python-site = {args.python_site}")
    if args.python_bin:
        print(f"[Override] --python-bin  = {args.python_bin}")

    # === PRE-BOOT GUARD ===
    validate_universe_id(universe_id)
    if not reboot:
        enforce_single_matrix_instance(universe_id)
    os.environ["UNIVERSE_ID"] = universe_id

    # === BOOT SESSION SETUP ===
    SwarmSessionRoot.inject_boot_args(site_root=PACKAGE_ROOT)

    session = SwarmSessionRoot()
    base_path = session.base_path
    agent_source = config['agent']
    pm = PathManager(root_path=base_path, site_root_path=PACKAGE_ROOT, agent_override=agent_source)


    # === POD & COMM ===
    pod_path = pm.get_path("pod", trailing_slash=False)
    comm_path = pm.get_path("comm", trailing_slash=False)
    os.makedirs(pod_path, exist_ok=True)
    os.makedirs(comm_path, exist_ok=True)

    # === REBOOT? ===
    if reboot:
        print("[REBOOT] 💣 Full MIRV deployment initiated.")
        Reaper(pod_root=pod_path, comm_root=comm_path).kill_universe_processes(universe_id)
        time.sleep(3)

    # === LOAD TREE ===
    if args.encrypted_directive and args.swarm_key:
        print(f"[BOOT] 🔐 Decrypting encrypted directive from {args.encrypted_directive}")
        matrix_directive = decrypt_directive(args.encrypted_directive, args.swarm_key)
    else:
        print(f"[BOOT] 📦 Loading plaintext directive: {boot_name}.py")
        matrix_directive = load_boot_directive(boot_name, path=config['boot_directives'])

    tp = TreeParser.load_tree_direct(matrix_directive)
    if not tp:
        print("[FATAL] Tree load failed. Invalid structure.")
        sys.exit(1)

    rejected_nodes=    tp.get_rejected_nodes()
    if rejected_nodes:
        print(f"[RECOVERY] ⚠️ Removed duplicate nodes: {rejected_nodes}")

    # === SPAWN CORE ===
    MATRIX_UUID = matrix_directive.get("universal_id", "matrix")

    cp = CoreSpawner(path_manager=pm, site_root_path=PACKAGE_ROOT, python_site=python_site, detected_python=python_exec, install_path=config["install_path"] )
    if verbose:
        cp.set_verbose(True)

    if debug:
        cp.set_debug(True)

    # 🔐 Generate Matrix's keypair and fingerprint
    matrix_keys = generate_agent_keypair()
    matrix_pub_obj = serialization.load_pem_public_key(matrix_keys["pub"].encode())
    fp = hashlib.sha256(matrix_keys["pub"].encode()).hexdigest()[:12]

    print(f"[TRUST] Matrix pubkey fingerprint: {fp}")

    swarm_key_b64 = generate_aes_key()
    matrix_key_b64 = generate_aes_key()

    # === Set up Matrix comm channel and trust ===
    comm_path =cp.ensure_comm_channel(MATRIX_UUID, [{}])

    matrix_keys = generate_agent_keypair()
    matrix_pub = matrix_keys["pub"]
    matrix_priv = matrix_keys["priv"]

    _matrix_priv_obj = RSA.import_key(matrix_keys["priv"])

    encryption_enabled = int(encryption_enabled)

    #sign and assign all the identities to the agents, priv/pub keys, private aes key, identity(which includes pubkey, universal_id, timestamp)
    tp.assign_identity_to_all_nodes(_matrix_priv_obj)

    #encryption is turned on here
    mode="encrypt"
    if not bool(encryption_enabled):
        mode = "plaintext_encrypt"

    #replace matrix pubkey/privkey with the original
    tp.assign_identity_token_to_node('matrix',
                                     matrix_priv_obj=matrix_keys["priv"],
                                     replace_keys={'priv_key': matrix_priv,
                                                   'pub_key': matrix_pub,
                                                   'private_key': matrix_key_b64}
                                     )


    matrix_node = tp.nodes.get("matrix")

    fb = Football()
    fb.set_identity_sig_verifier_pubkey(matrix_pub)
    fb.add_identity(matrix_node['vault'],
                    identity_name="agent_owner", #owner identity
                    verify_universal_id=True,      #make sure the name of the agent is the same as the one in the identity
                    universal_id="matrix",         #agent name to compare to the identity
                    is_payload_identity=True,         #yes, this payload is an identity; used during receiving packets; this will be the senders packet
                    sig_verifier_pubkey=matrix_pub,   #this pubkey is used to verify the identity, always Matrix's pubkey; used during sending packets
                    is_pubkey_for_encryption=False,    #if you turn on asymmetric encryption the pubkey contained in the identity will encrypt, check payload size
                    is_privkey_for_signing=True,       #use the privkey to sign the whole subpacket
                    )

    fb.set_use_symmetric_encryption(True)

    #fb.load_identity_file(comm_path, uuid="matrix", sig_pubkey=matrix_pub)
    #here is where we add Matrix AES Key to Encrypt and sign with Matrix Public Key
    fb.set_verify_signed_payload(True)
    fb.set_pubkey_verifier(matrix_pub)


    #matrix identity needs to be loaded as the target, because the pubkey is used to encrypt the aes key
    fb.load_identity_file(vault=matrix_node['vault'], universal_id='matrix')
    fb.set_aes_encryption_pubkey(matrix_pub)
    agent = DeliveryAgent()
    agent.set_crypto_handler(packet_encryption_factory(mode, fb))
    pk = Packet()
    pk.set_data({'agent_tree': tp.root})
    agent.set_location({"path": comm_path}) \
        .set_packet(pk) \
        .set_identifier("agent_tree_master") \
        .set_address(["directive"]) \
        .deliver()

    if args.encrypted_directive and args.swarm_key:
        print(f"[BOOT] 🔐 Decrypting encrypted directive from {args.encrypted_directive}")
        matrix_directive = decrypt_directive(args.encrypted_directive, args.swarm_key)
    else:
        print(f"[BOOT] 📦 Loading plaintext directive: {boot_name}")
        matrix_directive = load_boot_directive(boot_name)

    trust_payload = {
        "encryption_enabled": int(encryption_enabled),
        "pub": matrix_pub,
        "priv": matrix_priv,
        "swarm_key": swarm_key_b64,
        "private_key": matrix_key_b64,
        "matrix_pub": matrix_pub,
        "matrix_priv": matrix_priv,
        "security_box": {},
    }

    cp.set_keys(trust_payload)

    matrix_node['children'] = []
    # 🚀 Create pod and deploy Matrix
    new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
    cp.spawn_agent(new_uuid, MATRIX_UUID, MATRIX_UUID, "site_boot", matrix_node,  universe_id=universe_id)

    print("[✅] Matrix deployed at:", pod_path)
    print("[🔐] Matrix public key fingerprint:", fp)
    print("[🧠] The swarm is online.")
if __name__ == "__main__":
    main()