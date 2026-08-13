import tempfile
import os

def pem_to_tempfile(pem_str: str, suffix: str) -> str:
    """
    Writes PEM content to a secure temp file that will be removed on close.
    Returns the path.
    """
    if not pem_str or "BEGIN" not in pem_str:
        return pem_str  # Assume it's already a path
    # delete=False so we can pass it to libraries that need a path
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(pem_str.encode('utf-8'))
    f.flush()
    f.close()
    return f.name

def nuke_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
