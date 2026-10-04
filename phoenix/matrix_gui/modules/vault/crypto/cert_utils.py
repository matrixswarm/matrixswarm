"""Embed verified agent entry points and hash their exact bytes."""

import base64
import hashlib
from pathlib import Path
from matrix_gui.core.class_lib.paths.agent_root_selector import AgentRootSelector, LANG_EXT_MAP
from matrix_gui.core.class_lib.paths.source_policy import is_environment_path


def resolve_agent_source(agent_name: str, base_path: str, lang_hint: str = "python") -> str:
    return AgentRootSelector.find_agent_source(agent_name, lang_hint, base_path) or ""


def _source_path(node, base_path):
    source = node.get("src")
    if not source and base_path:
        name, lang = AgentRootSelector.agent_key(node)
        source = resolve_agent_source(name, base_path, lang)
    if not source or not Path(source).is_file():
        raise ValueError(f"Missing source for {node['name']}; select its source directory again.")
    if is_environment_path(source) or is_environment_path(Path(source).resolve()):
        raise ValueError("Environment files cannot be embedded as agent sources.")
    return str(Path(source).resolve())


def embed_agent_sources(directive, base_path=None):
    """Read every required source before modifying any node; never reuse stale embedded code."""
    pending = []
    contents = {}
    for node in AgentRootSelector.agent_nodes(directive):
        path = _source_path(node, base_path)
        if path not in contents:
            try:
                contents[path] = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            except OSError as exc:
                raise ValueError(f"Cannot read source for {node['name']}: {exc}") from exc
        pending.append((node, path, contents[path]))

    for node, path, encoded in pending:
        node["src"] = path
        node["src_embed"] = encoded


def set_hash_bang(directive, base_path=None):
    """Hash the bytes actually embedded, or a readable source when embedding is disabled."""
    pending = []
    for node in AgentRootSelector.agent_nodes(directive):
        if "src_embed" in node:
            try:
                source = base64.b64decode(node["src_embed"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid embedded source for {node['name']}.") from exc
            path = None
        else:
            path = _source_path(node, base_path)
            source = Path(path).read_bytes()
        pending.append((node, path, hashlib.sha256(source).hexdigest()))

    for node, path, digest in pending:
        if path:
            node["src"] = path
        node["hash_bang"] = digest
