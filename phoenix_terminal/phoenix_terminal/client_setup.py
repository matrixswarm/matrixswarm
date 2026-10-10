"""Credential-free client instructions and read-only connection diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import sys


def client_instructions(data_dir):
    """Use this runtime's interpreter, checkout and state; never include tokens."""
    source = str(Path(__file__).resolve().parents[1])
    state = str(Path(data_dir).resolve())
    if os.name == "nt":
        quote = lambda value: "'" + value.replace("'", "''") + "'"
        setup = [
            "# Run in PowerShell, not Bash. Change the client label if needed.",
            "Set-Location -LiteralPath " + quote(source),
            "$phoenixPy = " + quote(sys.executable),
            "$terminalState = " + quote(state),
        ]
        command = '& $phoenixPy -B -m phoenix_terminal --data-dir "$terminalState"'
    else:
        setup = [
            "# Run in a POSIX shell. Change the client label if needed.",
            "cd " + shlex.quote(source),
        ]
        command = (shlex.quote(sys.executable) + " -B -m phoenix_terminal --data-dir "
                   + shlex.quote(state))
    return "\n".join(setup + [
        command + " terminal doctor",
        command + " terminal request --label 'local-agent'",
        "# Wait for the human to approve in the Phoenix Terminal window.",
        command + " terminal status",
        "# Only use exact deployment IDs and operations returned after approval.",
        "# To read active swarms, if swarms.list is allowed:",
        "# " + command + " terminal swarms EXACT_DEPLOYMENT_ID",
        "# To inspect permitted cockpit tabs (sessions.list):",
        "# " + command + " terminal sessions EXACT_DEPLOYMENT_ID",
        "# Connect opens/reuses a cockpit tab (sessions.open); it does not boot a swarm:",
        "# " + command + " terminal connect EXACT_DEPLOYMENT_ID",
        "# Swarm inspection requires BOTH agents.list and logs.read:",
        "# " + command + " terminal inspect EXACT_DEPLOYMENT_ID",
        "# Railgun status reads a previous launch receipt; it does not request access.",
        "# Do not launch a swarm just to check connectivity.",
        "# Disconnect when finished:",
        "# " + command + " terminal disconnect",
    ]) + "\n"


def diagnose(data_dir):
    """Inspect only the selected endpoint; never request or renew approval."""
    from .terminal_client import TerminalClientIdentity, call_terminal

    directory = Path(data_dir).resolve()
    report = {
        "python": sys.executable,
        "module_directory": str(Path(__file__).resolve().parent),
        "data_directory": str(directory),
        "descriptor_present": (directory / "terminal-access.json").is_file(),
        "cockpit_descriptor_present": (directory / "cockpit-sessions.json").is_file(),
        "approval_requested": False,
    }
    if not report["descriptor_present"]:
        report.update(code="RUNTIME_NOT_FOUND", next_step=(
            "Use the data directory shown by the operator's Terminal window. "
            "The operator must open 'terminal open'; opening Phoenix GUI alone is insufficient."))
        return report
    try:
        endpoint = call_terminal(directory, "terminal.status", {}, timeout=3)
    except (OSError, RuntimeError, ValueError):
        report.update(code="RUNTIME_UNAVAILABLE", next_step=(
            "Check that the operator's Terminal window is open and this data directory matches it. "
            "A leftover descriptor does not prove that the runtime is running."))
        return report
    if endpoint.get("mode") != "terminal_connection_approval" or endpoint.get("accepting_requests") is not True:
        report.update(code="RUNTIME_NOT_ACCEPTING", next_step="Ask the operator to check Terminal access.")
        return report
    identity = TerminalClientIdentity(directory)
    if not identity.path.is_file():
        report.update(code="REQUEST_REQUIRED", next_step=(
            "Run 'terminal request --label YOUR_LABEL' using this same data directory, "
            "then wait for operator approval. Status and Railgun commands do not request access."))
        return report
    try:
        status = identity.status()
    except (OSError, RuntimeError, ValueError):
        report.update(code="CLIENT_IDENTITY_UNAVAILABLE", next_step=(
            "The saved client identity cannot be used with this runtime. If the operator reopened "
            "Terminal, run 'terminal request --label YOUR_LABEL' for a fresh approval. "
            "Do not delete or copy identity/token files to bypass a denial."))
        return report
    state = status.get("state")
    report["connection_state"] = state
    if state == "approved":
        report.update(code="APPROVED", next_step=(
            "Run 'terminal status' for permitted deployment IDs and operations. "
            "Approval alone does not prove remote connectivity or swarm health."))
    elif state == "pending":
        report.update(code="AWAITING_APPROVAL", next_step="Wait for the operator's Terminal approval dialog.")
    else:
        report.update(code="ACCESS_NOT_APPROVED", next_step=(
            "Ask the operator before requesting access again. Denial, expiry and disconnect "
            "do not grant access; do not try alternate identities."))
    return report
