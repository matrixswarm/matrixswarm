from pathlib import Path
import os

def resolve_matrixswarm_base():
    # 1. Env override
    env_path = os.getenv("MATRIXSWARM_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    # 2. .swarm pointer in cwd or parents
    here = Path.cwd()
    for parent in [here] + list(here.parents):
        swarm = parent / ".swarm"
        if swarm.exists():
            try:
                target = Path(swarm.read_text().strip()).expanduser().resolve()
                if (target / ".matrix").exists():
                    return target
            except Exception as e:
                print(f"[ERROR] Could not read .swarm file: {e}")

    # 3. Local .matrixswarm dir?
    possible = here / ".matrixswarm"
    if possible.exists() and (possible / ".matrix").exists():
        return possible

    # 4. Full fallback — DEV MODE
    print("[⚠ DEV MODE] No .swarm or valid .matrixswarm detected — using current working directory.")
    return here
