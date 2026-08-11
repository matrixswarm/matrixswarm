"""
Module: Agent Source Utilities

This module provides utility functions and constants for managing agent source files within a secure application framework.
It includes functionality for resolving agent source paths, embedding agent sources into directives, and embedding a cryptographic
hashbang for integrity verification.

Constants:
    - LANG_EXT_MAP: A mapping of programming languages to their corresponding file extensions.

Functions:
    - resolve_agent_source: Resolves the path to a specific agent source file in the `/agents` directory.
    - embed_agent_sources: Embeds source files of all required agents into a given directive.
    - set_hash_bang: Adds a cryptographic hashbang to ensure the integrity of an agent-based directive.

---

Constants:
    LANG_EXT_MAP = {
        "python": "py",
        "go": "go",
        "bash": "sh",
        "rust": "rs",
        "javascript": "js",
        "cpp": "cpp",
        "c": "c"
    }
        - A dictionary mapping supported programming languages to their respective file extensions.
"""

import base64, hashlib
from pathlib import Path
from matrix_gui.core.class_lib.paths.agent_root_selector import AgentRootSelector

# Language-to-extension map
LANG_EXT_MAP = {
    "python": "py",
    "go": "go",
    "bash": "sh",
    "rust": "rs",
    "javascript": "js",
    "cpp": "cpp",
    "c": "c"
}

def resolve_agent_source(agent_name: str, base_path: str, lang_hint: str = "python") -> str:
    """
    Resolves the file path to an agent source file within the `/agents` directory.

    This function searches for a source file matching the provided agent's name and language. It uses `LANG_EXT_MAP` to determine
    the appropriate file extension based on the specified language.

    Parameters:
        agent_name (str): Name of the agent to locate (e.g., "gatekeeper").
        agents_dir (str): Path to the `/agents` directory where the agent sources are expected to be located.
        lang (str): Programming language of the agent (default is "python").

    Returns:
        str: The absolute path to the resolved agent source file if found, or an empty string if the file is not found.

    Raises:
        FileNotFoundError: If the `/agents` directory does not exist or cannot be accessed.

    Example:
        >>> resolve_agent_source("gatekeeper", "/project/agents", "python")
        '/project/agents/gatekeeper.py'
    """
    return AgentRootSelector.find_agent_source(agent_name, lang_hint, base_path) or ""

def embed_agent_sources(directive, base_path=None):
    """
    Embeds the source files for all agents referenced in the provided directive into the directive itself.

    This function scans the directive for agent names, attempts to resolve their source file paths, and embeds the contents of those
    files into the directive. This ensures that all required agent files are bundled directly into the directive for portability and security.

    Parameters:
        directive (dict): The directive object, structured as a dictionary, containing the agent references to process.
        base_path (str): The base path where the `/agents` directory is located.

    Returns:
        None: The `directive` is modified in place with embedded source files.

    Raises:
        FileNotFoundError: If an agent source file cannot be found.
        ValueError: If the directive structure is invalid or missing required fields.

    Example:
        Input Directive:
        {
            "agents": [
                {"name": "gatekeeper", "lang": "python"},
                {"name": "data_processor", "lang": "rust"}
            ]
        }

        Modified Directive:
        {
            "agents": [
                {
                    "name": "gatekeeper",
                    "lang": "python",
                    "source": "<contents of gatekeeper.py>"
                },
                {
                    "name": "data_processor",
                    "lang": "rust",
                    "source": "<contents of data_processor.rs>"
                }
            ]
        }
    """

    if not directive or not isinstance(directive, dict):
        print(f"{directive}")
        return False

    print(f"[CLOWN-CAR][TRACE] scanning node: {directive.get('name')}")

    if isinstance(directive, dict):

        print(f"[CLOWN-CAR][TRACE] STARTING")

        agent_name = directive.get("name")
        src_path = directive.get("src")
        lang_hint = directive.get("lang", "python")

        if not src_path and agent_name and base_path:
            found = resolve_agent_source(agent_name, base_path, lang_hint)
            if found:
                directive["src"] = found
                src_path = found
            else:
                print(f"[CLOWN-CAR][ERROR] Missing source for {agent_name}")
                raise ValueError(f"[CLOWN-CAR][ERROR] Missing source for {agent_name}")


        if src_path and Path(src_path).exists():
            try:
                directive["src_embed"] = base64.b64encode(Path(src_path).read_bytes()).decode()
                print(f"[CLOWN-CAR] Embedded source for {agent_name}")
            except Exception as e:
                print(f"[CLOWN-CAR][WARN] Failed to embed {agent_name}: {e}")
                raise ValueError(f"[CLOWN-CAR][WARN] Failed to embed {agent_name}: {e}")
        else:
            if not directive.get("src_embed"):
                raise ValueError(f"[CLOWN-CAR][WARN] Failed to embed src_embed: {directive.get('name')}")

        # Recurse only into children
        for child in directive.get("children", []):
            embed_agent_sources(child, base_path=base_path)

    elif isinstance(directive, list):
        for item in directive:
            if not embed_agent_sources(item, base_path=base_path):
                raise ValueError(f"[CLOWN-CAR][WARN] Failed to embed")

def set_hash_bang(directive, base_path=None):
    """
    Embeds a cryptographic hashbang into the directive to ensure its integrity.
    [Full docstring provided above]
    """
    # Early exit for empty directives
    if not directive:
        return

    # Validate directive type
    if not isinstance(directive, (dict, list)):
        raise ValueError(f"Invalid directive: Expected dict or list, got {type(directive).__name__}")

    if isinstance(directive, dict):
        agent_name = directive.get("name")
        src_path = directive.get("src")
        lang_hint = directive.get("lang", "python")

        # Check for required keys (example - if "name" and "src" are essential)
        if not src_path and not agent_name:
            raise ValueError("Invalid directive: Missing required keys 'name' and/or 'src'.")

        # Resolve path if missing
        if not src_path and agent_name and base_path:
            found = resolve_agent_source(agent_name, base_path, lang_hint)
            if not found:
                raise ValueError(f"Unable to resolve source path for agent '{agent_name}' in base path '{base_path}'.")
            else:
                directive["src"] = found
                src_path = found

        # Hash embedded code first
        if "src_embed" in directive:
            try:
                src_bytes = base64.b64decode(directive["src_embed"])
            except Exception:
                raise ValueError("Invalid directive: 'src_embed' must be a valid Base64-encoded string.")
            directive["hash_bang"] = hashlib.sha256(src_bytes).hexdigest()
        elif src_path and Path(src_path).exists():
            directive["hash_bang"] = hashlib.sha256(Path(src_path).read_bytes()).hexdigest()

        # Recurse into children
        for child in directive.get("children", []):
            set_hash_bang(child, base_path=base_path)

    elif isinstance(directive, list):
        for item in directive:
            set_hash_bang(item, base_path=base_path)
