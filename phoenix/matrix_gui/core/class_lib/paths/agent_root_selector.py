"""Agent discovery shared by Clown Car validation, selection, and embedding."""

from pathlib import Path
import re
from .source_policy import is_environment_path


LANG_EXT_MAP = {
    "python": "py", "go": "go", "bash": "sh", "rust": "rs",
    "javascript": "js", "cpp": "cpp", "c": "c",
}


class AgentRootSelector:
    @staticmethod
    def agent_key(node):
        name = node.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name):
            raise ValueError("Every agent must have a plain source name, without paths or wildcards.")
        lang = str(node.get("lang", "python")).lower()
        if lang not in LANG_EXT_MAP:
            raise ValueError(f"Unsupported source language for {name}: {lang}")
        return name, lang

    @staticmethod
    def agent_nodes(directive):
        """Accept an agent tree, an agents wrapper, or a list; reject empty/invalid trees."""
        if isinstance(directive, dict) and "agents" in directive and "name" not in directive:
            directive = directive["agents"]
        roots = directive if isinstance(directive, list) else [directive]
        nodes = []
        seen = set()

        def visit(node):
            if not isinstance(node, dict):
                raise ValueError("Invalid agent tree: expected an agent object.")
            if id(node) in seen:
                raise ValueError("Invalid agent tree: repeated or cyclic node.")
            seen.add(id(node))
            AgentRootSelector.agent_key(node)
            children = node.get("children", [])
            if not isinstance(children, list):
                raise ValueError("Invalid agent tree: children must be a list.")
            nodes.append(node)
            for child in children:
                visit(child)

        for root in roots:
            visit(root)
        if not nodes:
            raise ValueError("No agents were supplied for source verification.")
        return nodes

    @staticmethod
    def resolve_agents_root(base_dir: str) -> Path:
        """Accept a monorepo, MatrixOS, agents/core folder, or an individual source folder."""
        base = Path(base_dir).expanduser().resolve()
        if not base.is_dir():
            raise FileNotFoundError(f"Not an agent source directory: {base_dir}")
        for relative in ("matrixos/agents", "agents"):
            if (base / relative).is_dir():
                return base / relative
        # Preserve an explicitly selected package/core/custom folder. Broadening it
        # to its parent could select a different copy of the agent.
        return base

    @staticmethod
    def find_agent_source(agent_name: str, lang: str, base_dir: str) -> str | None:
        name, lang = AgentRootSelector.agent_key({"name": agent_name, "lang": lang})
        root = AgentRootSelector.resolve_agents_root(base_dir)
        if (root / f"{lang}_core").is_dir():
            root = root / f"{lang}_core"
        filename = f"{name}.{LANG_EXT_MAP[lang]}"

        # Prefer explicit conventional entry points over nested helper files.
        matches = [p for p in (root / filename, root / name / filename) if p.is_file()]
        if not matches:
            matches = [p for p in root.rglob(filename) if p.is_file()]
        if not matches and lang == "python":
            folders = ([root] if root.name == name else []) + list(root.rglob(name))
            matches = [p / "__init__.py" for p in folders if (p / "__init__.py").is_file()]
        unique = sorted({str(p.resolve()) for p in matches
                         if not is_environment_path(p) and not is_environment_path(p.resolve())})
        if len(unique) > 1:
            raise ValueError(f"Multiple sources found for {name}; select that agent's exact directory.")
        return unique[0] if unique else None

    @staticmethod
    def verify_all_sources(directive_root, base_dir: str) -> list[str]:
        selection = AgentSourceSelection(directive_root)
        selection.add_directory(base_dir)
        return selection.missing_agents


class AgentSourceSelection:
    """Collect readable sources across folders without changing the directive until complete."""

    def __init__(self, directive):
        self.nodes = AgentRootSelector.agent_nodes(directive)
        self.required = list(dict.fromkeys(AgentRootSelector.agent_key(node) for node in self.nodes))
        self.sources = {}
        self.origins = {}
        self.errors = {}
        self._directories = []

    @staticmethod
    def _check_readable(path):
        if is_environment_path(path) or is_environment_path(Path(path).resolve()):
            raise PermissionError("Environment files cannot be used as agent sources.")
        if not Path(path).is_file():
            raise FileNotFoundError(f"Source file no longer exists: {path}")
        with Path(path).open("rb") as source:
            source.read(1)

    @property
    def missing_agents(self):
        return [f"{name} ({lang})" for name, lang in self.required if (name, lang) not in self.sources]

    @property
    def roots(self):
        used = set(self.origins.values())
        return [directory for directory in self._directories if directory in used]

    def refresh(self):
        """Recheck retained files so stale paths never count as resolved."""
        for key, path in list(self.sources.items()):
            try:
                self._check_readable(path)
            except OSError as exc:
                del self.sources[key]
                self.origins.pop(key, None)
                self.errors[key] = str(exc)

    def add_directory(self, directory):
        self.refresh()
        root = str(AgentRootSelector.resolve_agents_root(directory))
        for key in self.required:
            if key in self.sources:
                continue
            try:
                path = AgentRootSelector.find_agent_source(*key, root)
                if not path:
                    continue
                self._check_readable(path)
            except (OSError, ValueError) as exc:
                self.errors[key] = str(exc)
                continue
            self.sources[key] = path
            self.origins[key] = root
            self.errors.pop(key, None)
        if root not in self._directories:
            self._directories.append(root)
        return not self.missing_agents

    def apply(self):
        self.refresh()
        if self.missing_agents:
            raise ValueError("Missing agent sources: " + ", ".join(self.missing_agents))
        for node in self.nodes:
            node["src"] = self.sources[AgentRootSelector.agent_key(node)]
