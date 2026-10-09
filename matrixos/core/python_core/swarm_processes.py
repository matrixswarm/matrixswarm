"""Shared process observation for MatrixD and the read-only cockpit service."""
from pathlib import Path
import re
import psutil


def get_all_swarm_agent_info(universe=None, base="/matrix"):
    """
    Scan running swarm agents and extract:
    - universe
    - reboot_uuid
    - universal_id
    - pod_path
    - comm_path

    Optional: pass a universe name to filter only that swarm.
    """
    base_root = str(base).replace("\\", "/").rstrip("/") or "/"
    runtime_pattern = re.compile(
        rf"{re.escape(base_root)}/universes/runtime/"
        r"(?P<universe>[a-zA-Z0-9_\-]+)/"
        r"(?P<reboot>[0-9_]+)/pod/(?P<uuid>[a-f0-9\-]+)/run\s+"
        r"--job(?:=|\s+)"
        r"(?P<job_universe>[a-zA-Z0-9_\-]+):"
        r"(?P<universal_id>[a-zA-Z0-9_\-]+)"
    )
    job_pattern = re.compile(
        r"^(?P<job_universe>[a-zA-Z0-9_\-]{1,32}):"
        r"(?P<universal_id>[a-zA-Z0-9_\-]+)$"
    )
    protected_launcher = (
        Path(base_root) / "core" / "python_core" / "protected_launcher.py"
    ).as_posix()

    def extract_job(cmdline_parts):
        for index, value in enumerate(cmdline_parts):
            if value == "--job" and index + 1 < len(cmdline_parts):
                return job_pattern.fullmatch(str(cmdline_parts[index + 1]))
            if str(value).startswith("--job="):
                return job_pattern.fullmatch(str(value).split("=", 1)[1])
        return None

    def runtime_details(cmdline, proc, job_universe, universal_id):
        match = runtime_pattern.search(cmdline)
        if match and match.group("universe") == job_universe:
            return match.group("reboot")

        # Protected processes intentionally expose only the fixed launcher and
        # the universe-scoped --job label. Root matrixd may use the private
        # launch-path environment entry to recover the graceful-shutdown comm
        # directory; PID termination remains available if /proc denies it.
        try:
            run_path = (proc.environ() or {}).get("MATRIX_AGENT_RUN_PATH", "")
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            run_path = ""
        if run_path:
            protected_cmdline = f"{run_path} --job {job_universe}:{universal_id}"
            match = runtime_pattern.search(protected_cmdline)
            if match and match.group("universe") == job_universe:
                return match.group("reboot")

        # The protected launcher removes its private path from the live Python
        # environment. Locate the matching comm directory instead; UUIDs are
        # unique inside a universe, so this retains graceful die-cookie
        # shutdown without disclosing the source path on the command line.
        runtime_universe = Path(base) / "universes" / "runtime" / job_universe
        try:
            boots = sorted(
                (
                    child for child in runtime_universe.iterdir()
                    if child.name != "latest"
                    and child.is_dir()
                    and re.fullmatch(r"[0-9_]+", child.name)
                ),
                key=lambda child: child.name,
                reverse=True,
            )
            for boot in boots:
                if (boot / "comm" / universal_id).is_dir():
                    return boot.name
        except (FileNotFoundError, PermissionError, OSError):
            pass

        return None

    results = []

    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline_parts = [str(value) for value in (proc.info.get('cmdline') or [])]
            job_match = extract_job(cmdline_parts)
            if not job_match:
                continue
            job_universe = job_match.group("job_universe")
            universal_id = job_match.group("universal_id")
            if universe and job_universe != universe:
                continue

            cmdline = " ".join(cmdline_parts)
            direct_match = runtime_pattern.search(cmdline)
            if direct_match and (
                direct_match.group("universe") != job_universe
                or direct_match.group("job_universe") != job_universe
                or direct_match.group("universal_id") != universal_id
            ):
                direct_match = None
            approved_launcher = bool(
                direct_match or protected_launcher in cmdline_parts
            )
            if not approved_launcher:
                continue

            reboot_uuid = runtime_details(
                cmdline, proc, job_universe, universal_id
            )
            runtime_root = (
                Path(base) / "universes" / "runtime" / job_universe / reboot_uuid
                if reboot_uuid
                else None
            )

            results.append({
                "pid": proc.info['pid'],
                "process_started_at": proc.create_time(),
                "universe": job_universe,
                "reboot_uuid": reboot_uuid,
                "universal_id": universal_id,
                "pod_path": str(runtime_root / "pod") if runtime_root else None,
                "comm_path": str(runtime_root / "comm") if runtime_root else None,
                "details": {"cmd": cmdline},
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, TypeError):
            continue

    return results
