"""Files that must never be collected from an operator's source checkout."""

from fnmatch import fnmatchcase
from pathlib import Path


ENVIRONMENT_FILE_PATTERNS = (".env*", "*.env", "*.env.*")


def is_environment_path(path):
    """Exclude env files, variants, backups and enclosing env directories."""
    return any(
        fnmatchcase(part.casefold(), pattern)
        for part in Path(path).parts
        for pattern in ENVIRONMENT_FILE_PATTERNS
    )
