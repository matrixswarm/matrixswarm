#!/usr/bin/env python3
"""Publish immutable source downloads from checked main commits (Linux host)."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request
import zipfile

REPOSITORY = "matrixswarm/matrixswarm"
API = "https://api.github.com/repos/" + REPOSITORY
CHECKS = {".github/workflows/security-checks.yml", ".github/workflows/phoenix-process-tests.yml"}
LIMIT = 512 * 1024 * 1024


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        "User-Agent": "MatrixSwarm-Download-Publisher",
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache",
        "X-GitHub-Api-Version": "2022-11-28",
    }), timeout=60)


def api(path):
    with request(API + path) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("GitHub metadata exceeds limit")
    return json.loads(data)


def write(path, data, *, immutable=False):
    if path.exists() and immutable:
        if path.read_bytes() != data:
            raise ValueError("Refusing to replace published content: " + path.name)
        return
    fd, name = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def checks_passed(sha):
    runs = api("/actions/runs?event=push&head_sha=" + sha + "&per_page=100")["workflow_runs"]
    for path in CHECKS:
        matching = [r for r in runs if r.get("path") == path
                    and r.get("head_sha") == sha and r.get("head_branch") == "main"]
        if not matching:
            return False
        newest = max(matching, key=lambda r: (r["id"], r.get("run_attempt", 1)))
        if newest.get("status") != "completed" or newest.get("conclusion") != "success":
            return False
    return True


def publish(destination, bootstrap_commit=None):
    destination.mkdir(parents=True, exist_ok=True, mode=0o755)
    # One writer across cron, manual recovery, and slow archive downloads.
    with (destination / ".publisher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another publication is in progress")
            return
        commit = api("/commits/main")
        main_sha = commit["sha"]
        latest = destination / "latest.json"
        if bootstrap_commit is not None:
            if latest.exists():
                raise ValueError("Bootstrap is only allowed before the first publication")
            if not re.fullmatch(r"[0-9a-f]{40}", bootstrap_commit):
                raise ValueError("Bootstrap requires a full commit ID")
            comparison = api("/compare/" + bootstrap_commit + "..." + main_sha)
            if comparison.get("status") not in {"ahead", "identical"}:
                raise ValueError("Bootstrap commit must be an ancestor of main")
            commit = api("/commits/" + bootstrap_commit)
            if commit["sha"] != bootstrap_commit:
                raise ValueError("Bootstrap commit did not match")
        sha = commit["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid commit ID")
        if latest.exists() and json.loads(latest.read_text())["commit"] == sha:
            print("Current download already published: " + sha[:12])
            return
        if not checks_passed(sha):
            print("Waiting for security and Phoenix checks: " + sha[:12])
            return
        timestamp = dt.datetime.fromisoformat(commit["commit"]["committer"]["date"].replace("Z", "+00:00"))
        version = timestamp.astimezone(dt.timezone.utc).strftime("%Y.%m.%d") + "-" + sha
        basename = "matrixswarm-" + version
        archive = destination / (basename + ".zip")
        if not archive.exists():
            fd, name = tempfile.mkstemp(prefix=".archive-", dir=destination)
            try:
                with os.fdopen(fd, "wb") as out, request(
                        "https://codeload.github.com/" + REPOSITORY + "/zip/" + sha) as response:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > LIMIT:
                            raise ValueError("Archive exceeds publication limit")
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                with zipfile.ZipFile(name) as zipped:
                    members = zipped.namelist()
                    prefix = "matrixswarm-" + sha + "/"
                    if not members or any(not entry.startswith(prefix) or ".." in entry.split("/") for entry in members):
                        raise ValueError("Archive does not match requested commit")
                os.chmod(name, 0o644)
                os.replace(name, archive)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        hashes = {name: hashlib.new(name) for name in ("sha256", "sha512")}
        with archive.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                for digest in hashes.values():
                    digest.update(chunk)
        digests = {key: digest.hexdigest() for key, digest in hashes.items()}
        for algorithm, digest in digests.items():
            write(destination / (archive.name + "." + algorithm),
                  (digest + "  " + archive.name + "\n").encode(), immutable=True)
        manifest = {"schema_version": 1, "version": version, "commit": sha,
                    "commit_date": commit["commit"]["committer"]["date"],
                    "filename": archive.name, "bytes": archive.stat().st_size, **digests}
        encoded = (json.dumps(manifest, indent=2) + "\n").encode()
        write(destination / (basename + ".json"), encoded, immutable=True)
        # Avoid making an older build current if main advanced during transfer.
        if api("/commits/main")["sha"] != main_sha:
            print("Main advanced; retaining prior latest pointer until the next run")
            return
        write(latest, encoded)
        print("Published " + archive.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--bootstrap-commit", help="Seed an empty download directory with a checked main ancestor")
    args = parser.parse_args()
    publish(args.destination.resolve(), args.bootstrap_commit)
