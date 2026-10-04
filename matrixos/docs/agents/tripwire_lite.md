#### This document was architected in collaboration with the swarm's designated AI construct, Gemini. 
#### Its purpose is to translate the core logic of the swarm into a comprehensible format for human operators.

# Agent Reference: Tripwire Lite

The `tripwire_lite` agent acts as a real-time file integrity monitor. It uses the `inotify` library to watch specified directories and logs any changes, creations, or deletions that occur within them. This makes it an essential tool for security and for monitoring critical application code for unauthorized changes.

---
## How it Works

The agent initializes the `inotify` adapter and adds a "watch" on a list of directories. It then enters a continuous loop, listening for filesystem events. When an event occurs (like a file being modified or deleted), it logs the event type and the full path of the affected file. To prevent log spam, it has a 60-second cooldown period for reporting events on the same file path.

---
## Configuration

To use the `tripwire_lite` agent, add it to your directive. You can customize the directories it watches through the `config` block.

**Configurable Options:**

* **`watch_paths`**: A list of directory paths (relative to the `SITE_ROOT`) that the agent should monitor. If not provided, it defaults to monitoring key swarm directories like `agent`, `core`, and `boot_directives`.

### Quarantine storage

Leave `quarantine_root` empty or omit it to use
`<agent static_comm_path_resolved>/quarantine`, beside the agent's logs and alert
history. The directory is scoped to the universe boot and agent and is writable
by the swarm's service account. New directories use owner-only permissions.

Existing directives containing the former default `/matrix/quarantine` also
resolve to automatic storage. The resolved path is logged at initialization and
included in the status response. Existing files at the former path stay there.
Other configured paths are used as supplied and require suitable permissions.

Dry-run and detect-only modes do not create the directory. Active enforcement
also requires permission to move files out of the watched source directories.
Tripwire ignores its own quarantine directory to avoid processing moved files
again. An initialization failure stops startup and reports the original error.

### Example Directive

This directive launches a `tripwire_lite` agent to monitor the `/var/www` and `/etc/nginx` directories.

```python
# /boot_directives/tripwire_demo.py

matrix_directive = {
    "universal_id": "matrix",
    "name": "matrix",
    "children": [
        {
            "universal_id": "tripwire-1",
            "name": "tripwire_lite",
            "config": {
                "watch_paths": [
                    "/var/www",
                    "/etc/nginx"
                ]
            }
        }
    ]
}
```
### Launch Command:

python3 site_ops/site_boot.py --universe security --directive tripwire_demo

