# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import os, time, posixpath, stat
from log_watcher.factory.utility.parse_results import parse_results

def tail_file(path, n=500, block_size=8192):
    """
    True end-of-file tailer.
    Reads the last `n` lines from `path` without pulling the head.
    """
    lines = []
    # Nonblocking open prevents a mistaken FIFO path from hanging the agent.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("expected a regular log file, not a directory or device")
        f = os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise
    with f:
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        block_end = file_size
        buffer = b""
        floor = max(0, file_size - 1024 * 1024)
        while len(lines) <= n and block_end > floor:
            read_size = min(block_size, block_end - floor)
            block_end -= read_size
            f.seek(block_end)
            buffer = f.read(read_size) + buffer
            lines = buffer.splitlines()

    # A bounded tail may start in the middle of a line; omit that fragment.
    capped = floor > 0 and block_end == floor and len(lines) <= n
    if block_end > 0:
        lines = lines[1:]
    result = [l.decode("utf-8", errors="replace") for l in lines[-n:]]
    if capped:
        result.insert(0, "[collector notice: tail limited to the last 1 MiB]")
    return result

def collect_log(log=None, cfg=None):
    """
    Shared log reader.
    Handles file tailing, in-memory text, or list of lines.
    Returns parsed summary via parse_results().
    """
    cfg = cfg or {}
    max_lines = int(cfg.get("max_lines", 500))
    rotate_depth = int(cfg.get("rotate_depth", 1))
    rotation_style = cfg.get("rotation_style", "dated")
    if not 1 <= max_lines <= 5000 or not 0 <= rotate_depth <= 30:
        raise ValueError("max_lines must be 1–5000; rotate_depth must be 0–30")
    if rotation_style not in {"dated", "numbered"}:
        raise ValueError("rotation_style must be dated or numbered")
    results = []

    # Direct in-memory log data
    if isinstance(log, list):
        results = log[-max_lines:]
        return parse_results(results)

    if isinstance(log, str) and not os.path.exists(log):
        results = log.splitlines()[-max_lines:]
        return parse_results(results)

    # File or configured paths
    paths = []
    if isinstance(log, str) and os.path.exists(log):
        paths = [log]
    elif cfg.get("paths"):
        paths = cfg["paths"]

    if not isinstance(paths, list) or not 1 <= len(paths) <= 16:
        raise ValueError("configure 1–16 absolute log file paths")
    errors = []
    for path in paths:
        if (not isinstance(path, str) or not posixpath.isabs(path)
                or "\x00" in path or any(c in path for c in "*?[]")
                or len(path.encode("utf-8")) > 1024):
            raise ValueError("paths must contain absolute Linux file paths without wildcards")
        if path.endswith((".gz", ".xz", ".bz2", ".zip")):
            errors.append(f"[collector error: compressed log not supported: {path}]")
            continue
        for i in range(rotate_depth + 1):
            suffix = "" if i == 0 else (f".{i}" if rotation_style == "numbered" else
                f"-{time.strftime('%Y%m%d', time.localtime(time.time() - i*86400))}")
            file_path = f"{path}{suffix}"
            try:
                # Read from end of file precisely
                results.extend(tail_file(file_path, n=max_lines))
            except FileNotFoundError:
                # Missing rotations are normal; a missing configured base is not.
                if i == 0:
                    errors.append(f"[collector error: file missing: {file_path}]")
            except Exception as e:
                errors.append(f"[collector error: {file_path}: {e}]")

    parsed = parse_results(results)
    if errors:
        parsed["lines"] = errors + parsed["lines"]
        detail = parsed["summary"] if results else "No log lines could be collected."
        parsed["summary"] = f"Incomplete collection: {len(errors)} file error(s). " + detail
    return parsed
