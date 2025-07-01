#### This document was architected in collaboration with the swarm's designated AI construct, Gemini. 
#### Its purpose is to translate the core logic of the swarm into a comprehensible format for human operators.

# MatrixSwarm Architecture

This document provides a high-level overview of the MatrixSwarm architecture, from the initial boot sequence to inter-agent communication. Understanding these core concepts is key to developing for and extending the swarm.

---
## 1. The Boot Process

The entire swarm is brought to life by the `site_boot.py` script. This process is designed to be secure, configurable, and robust.

1.  **Initiation**: A user runs `python3 site_ops/site_boot.py --universe <id> --directive <name>`.
2.  **Directive Loading**: The script loads the specified directive file (e.g., `gatekeeper-demo.py`) from the `/boot_directives` directory. This file contains the Python dictionary that defines the entire agent hierarchy.
3.  **Tree Parsing**: The `TreeParser` class is initialized with the directive. It recursively walks through the agent tree to:
    * Validate the structure and remove any malformed nodes.
    * Detect and reject any agents with duplicate `universal_id` values.
    * Assign a unique cryptographic identity (a **Vault**) to every single node in the tree. This Vault contains the agent's new public/private key pair and an identity token signed by the master "Matrix" agent's private key.
4.  **Spawning the Core**: The `CoreSpawner` class is initialized with the system's Python environment details.
5.  **Matrix Launch**: Finally, `site_boot.py` uses the `CoreSpawner` to launch the root `matrix` agent. This is the only agent launched directly by the boot script. All other agents are subsequently launched by their "parent" agent within the swarm.

---
## 2. Secure Agent Spawning

To avoid exposing sensitive information (like private keys) during agent creation, MatrixSwarm uses a secure spawning mechanism powered by `ghost_vault.py`.

1.  **Payload Assembly**: When an agent (like Matrix) decides to spawn a child, its `CoreSpawner` gathers all necessary configuration data for the new agent—paths, arguments, and its unique cryptographic **Vault**—into a single Python dictionary called a `payload`.
2.  **Encryption**: The spawner calls the `build_encrypted_spawn_env()` function. This function:
    * Generates a secure, single-use AES-256 key.
    * Encrypts the entire `payload` dictionary with this key.
    * Saves the resulting ciphertext to a temporary `.vault` file.
3.  **Secure Handoff**: The spawner launches the new agent as a `subprocess.Popen` command. It passes only two environment variables to the new process:
    * `VAULTFILE`: The path to the temporary encrypted `.vault` file.
    * `SYMKEY`: The single-use AES key needed to decrypt the vault.
4.  **Cleanup**: The `CoreSpawner` does not hold onto the key. The key exists only for the new agent process, ensuring a secure handoff of credentials.

---
## 3. The Agent Lifecycle

Every agent in the swarm, regardless of its function, is built on the `BootAgent` class, which dictates its lifecycle.

1.  **Waking Up**: The first thing a newly spawned agent process does is call `decrypt_vault()`. It reads the `VAULTFILE` and `SYMKEY` from its environment, decrypts its configuration payload, and loads its identity, keys, and paths into memory.
2.  **Starting Threads**: With its configuration loaded, the agent immediately starts several background threads to manage its core functions:
    * **`heartbeat`**: Periodically writes a timestamp to a file in its `/comm` directory to signal to the swarm that it's alive.
    * **`packet_listener`**: Constantly watches its `/comm/incoming` directory for new command files from other agents.
    * **`spawn_manager`**: If the agent has children defined in its directive, this thread monitors them. If a child agent goes silent (stops producing heartbeats), this thread will automatically re-spawn it using the **Secure Agent Spawning** process described above.
    * **`worker`**: This is the main thread where the agent's unique logic is executed. Developers override the `worker()` method to define what an agent actually does.

---
## 4. The Packet Delivery System

Agents do not communicate through traditional network sockets or APIs. Instead, they use a secure, file-based messaging queue.

1.  **Packet Creation**: An agent wanting to send a message creates a `Packet` object. This object contains a `handler` (the function the receiving agent should run) and a `content` payload.
2.  **Secure Delivery**: The sending agent uses a `DeliveryAgent`. This agent:
    * Takes the `Packet` and uses a cryptographic "Football" object to encrypt and sign the contents with the sender's identity.
    * Writes the resulting encrypted JSON to a temporary file.
    * Performs an **atomic** `os.replace` to move the temporary file into the target agent's `/comm/incoming` directory. This atomic operation prevents the receiver from ever reading a partially written file.
3.  **Reception and Processing**: The receiving agent's `packet_listener` thread detects the new file. It uses a `ReceptionAgent` to:
    * Read the encrypted file.
    * Use its own "Football" to decrypt the content and, most importantly, cryptographically verify the sender's signature against the master Matrix public key.
    * If the signature is valid, it passes the packet's `handler` and `content` to the agent's main logic for processing.
 ---
## The Service Manager: Role-Based Service Discovery

To prevent agents from being tightly coupled (e.g., forcing the `apache_watchdog` to know the specific `universal_id` of a `discord_relay`), MatrixSwarm uses a **role-based service discovery** system. Agents don't need to know about each other by name; they only need to know about the *role* or *function* they require.

This system is defined by the `service-manager` block within an agent's `config` in a directive.

### The Service Provider

## The Service Manager: Advanced Role-Based Service Discovery

To prevent agents from being tightly coupled (e.g., forcing the `apache_watchdog` to know the specific `universal_id` of a `discord_relay`), MatrixSwarm uses a **role-based service discovery** system. Agents don't need to know about each other by name; they only need to know about the *role* or *function* they require.

This system is defined by the `service-manager` block within an agent's `config` in a directive.

---
### The Service Provider

An agent that can perform a specific task "advertises" its capabilities by defining them in its `service-manager` block.

For example, the `discord_relay` agent in the `gatekeeper-demo.py` directive advertises that it can handle communication and alerts.

```python
# From gatekeeper-demo.py
"config": {
    "bot_token": os.getenv("DISCORD_TOKEN"),
    "channel_id": os.getenv("DISCORD_CHANNEL_ID"),
    "service-manager": [{
        "role": ["comm", "comm.security", "hive.alert.send_alert_msg", "comm.*"],
        "scope": ["parent", "any"],
        "auth": {"sig": True},
        "priority": 10,
        "exclusive": False
    }]
}
```

role: A list of function names this agent can perform. hive.alert.send_alert_msg is a role that means "able to send an alert."

scope: Defines which other agents this service is available to.

The Service Consumer
An agent that needs a function performed (like sending an alert) does not look for a specific agent. Instead, it asks the swarm for any agent that can fulfill the required role.

The apache_watchdog agent does exactly this in its alert_operator function.
Python

### From apache_watchdog.py
def alert_operator(self, message=None):
    # ... (packet creation code) ...

    # Ask the swarm: "Find all agents that can handle this role."
    alert_nodes = self.get_nodes_by_role("hive.alert.send_alert_msg")
    if not alert_nodes:
        self.log("[WATCHDOG][ALERT] No alert-compatible agents found.")
        return

    # Send the packet to every agent that responded.
    for node in alert_nodes:
        # ... (delivery agent code) ...
        
### The Benefit: A Decoupled and Flexible Swarm
This architecture is incredibly flexible. If you decide you want alerts to go to Telegram instead of Discord, you don't need to modify the apache_watchdog agent's code. You simply update your directive: remove the service-manager block from the Discord agent and add it to the telegram_relay agent.

The watchdog will continue to ask for the "hive.alert.send_alert_msg" role, and the swarm will now direct its request to the Telegram agent. This allows you to hot-swap service providers and reconfigure the swarm's behavior without ever touching the underlying agent code.

---
## Dynamic Agent Configuration (Real-Time Updates)
A standout feature of MatrixSwarm is the ability to change an agent's configuration while it is running. This is handled by the _throttled_worker_wrapper method in BootAgent, which every agent inherits.

How it Works
Config Directory: Every agent has a dedicated /comm/{universal_id}/config/ directory.

Monitoring: The _throttled_worker_wrapper function constantly monitors this directory for new .json files.

Update Trigger: To update an agent, you simply drop a new JSON file into its /config directory. This file contains the new configuration dictionary.

Secure Loading: The wrapper detects the new file, securely decrypts it using the swarm's encryption protocols, and loads its content.

Injection into Worker: This new config dictionary is then passed as the config argument into the very next execution of the agent's worker() method.

Cleanup: After the new configuration is loaded, the .json file is deleted from the /config directory.

This allows for live, dynamic tuning of the entire swarm. For example, you could drop a new config file into a redis_watchdog's folder to change its check_interval_sec from 10 seconds to 60 seconds without ever stopping or restarting the agent.

---


## Universe Segregation: The Swarm Session

A core feature of MatrixSwarm is its ability to run multiple, completely isolated "universes" on the same machine without conflict. This is achieved through a session-based directory structure managed by two key components: `SwarmSessionRoot` and `PathManager`.

### The Session Root (`SwarmSessionRoot`)

When `site_boot.py` initiates a new swarm, it first creates a `SwarmSessionRoot` object. This class acts as a **singleton**, meaning there is only one instance of it for the entire boot process. Its job is to establish the unique, segregated "world" for that specific swarm instance.

1.  **Unique Path Creation**: It generates a unique base path using the `universe_id` and a current timestamp (the `reboot_uuid`). This creates the segregated directory structure: `/matrix/<universe_id>/<YYYYMMDD_HHMMSS>/`.
2.  **Core Directories**: Inside this unique base path, it immediately creates the two fundamental directories for the swarm's operation: `.../comm/` and `.../pod/`.
3.  **The "Latest" Symlink**: To make it easy to find the most recent session for a given universe, `SwarmSessionRoot` creates a symbolic link (`symlink`). This link points from a stable path to the timestamped session directory: `/matrix/<universe_id>/latest` → `/matrix/<universe_id>/<YYYYMMDD_HHMMSS>/`. The `resolve_latest_symlink` function can also be used to repair this link if it's broken.

### The Path Manager (`PathManager`)

While `SwarmSessionRoot` *creates* the session, the `PathManager` *distributes* this information to the rest of the system.

When components like `CoreSpawner` or `BootAgent` need to know where the `comm` or `pod` directories are, they instantiate a `PathManager` with the `use_session_root=True` flag.

The `PathManager` then communicates with the `SwarmSessionRoot` singleton to get the correct, session-specific paths. This ensures that every component, from the spawner to the individual agents, is operating within the same segregated "world" that was created at boot time.

Together, these two files guarantee that every swarm instance is self-contained, preventing agents from different universes or different boot sessions from ever interfering with one another.     