import tempfile, os, atexit

_temp_files = []

def _write_pem_temp(label: str, pem_str: str, suffix=".pem") -> str:
    if not pem_str:
        return None
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=f"{label}_")
    f.write(pem_str.replace("\\n", "\n").encode())
    f.flush()
    f.close()
    _temp_files.append(f.name)
    return f.name

def _cleanup_tempfiles():
    for path in _temp_files:
        try: os.unlink(path)
        except: pass
    _temp_files.clear()

atexit.register(_cleanup_tempfiles)
