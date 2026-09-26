"""Static discovery without importing dialogs or activating production services."""
import ast
import hashlib

from .catalog import BEHAVIORAL_ADAPTERS, RELEASE_GAPS


def inventory(root):
    surfaces, errors = [], []
    digest = hashlib.sha256()
    for path in sorted((root / "phoenix").rglob("*.py")):
        if any(part in {".venv", "__pycache__", ".git"} for part in path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            content = path.read_bytes()
            digest.update(relative.encode() + b"\0" + content + b"\0")
            tree = ast.parse(content.decode("utf-8-sig"))
        except (SyntaxError, UnicodeError, OSError) as exc:
            errors.append({"file": relative, "error": str(exc)})
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [ast.unparse(base) for base in node.bases]
            methods = [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
            key = f"{relative}:{node.name}"
            # Includes name-based candidates for indirect subclasses/custom panels.
            if not (any(any(term in base for term in ("QDialog", "QWidget", "QMainWindow", "QThread", "QRunnable", "Thread", "BaseEditor")) for base in bases)
                    or any(term in node.name for term in ("Dialog", "Panel", "Worker", "Process"))
                    or key in BEHAVIORAL_ADAPTERS):
                continue
            surfaces.append({"id": key, "line": node.lineno, "bases": bases, "methods": methods,
                             "adapter": BEHAVIORAL_ADAPTERS.get(key),
                             "coverage": "partial-behavioral" if key in BEHAVIORAL_ADAPTERS else "unmapped"})
    found = {item["id"] for item in surfaces}
    return {"surfaces": surfaces, "parse_errors": errors,
            "phoenix_source_sha256": digest.hexdigest(),
            "stale_adapters": sorted(set(BEHAVIORAL_ADAPTERS) - found),
            "release_gaps": list(RELEASE_GAPS),
            "note": "Static candidates, not a proof of exhaustive functionality discovery or behavioral coverage."}
