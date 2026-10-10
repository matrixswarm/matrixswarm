"""Trusted interpretation hints; log text never supplies instructions or authority."""
import re


LIFECYCLE_CODES = {"HEARTBEAT_FAILURE", "PUNJI_DROPPED", "PUNJI_DROP_FAILED"}
CARDS = {
    "THREAD_HEARTBEAT_STALE": {
        "meaning": "A named worker's current-process heartbeat file exceeded its declared timeout. Another live worker can keep the agent process present.",
        "next_read": "Report immediately with thread, last heartbeat, timeout and observation time. Compare work progress and logs in at most one follow-up read; this does not prove a dead or unrecoverable process.",
    },
    "SPAWN_BURST": {
        "meaning": "At least three spawn records were observed within the last 60 seconds. Counts include the initial spawn and use file modification times; causes and recovery remain unverified.",
        "next_read": "Report immediately with agent ID, count and timestamps. Correlate with work failures and punji evidence; do not assume every spawn was a crash or initiate a restart.",
    },
    "PROCESS_HEALTH_INCOMPLETE": {
        "meaning": "Thread or spawn evidence was missing, unreadable, rejected, incomplete or could not be tied to the current process.",
        "next_read": "State the coverage limit. Missing evidence is not proof of a failed worker, and an observed subset does not prove all expected threads exist.",
    },
    "WORK_BLOCKED": {
        "meaning": "The agent reports a failed operation with a fixed blocked reason and consecutive failure count, independently of heartbeat liveness. A watch_setup failure can mean partial watch coverage; it does not by itself prove every watch is inactive or the whole agent is critically unusable.",
        "next_read": "Report immediately. Read that agent's logs/progress once if needed to compare timestamps and outcomes. An idle or successful different operation does not clear this failure.",
    },
    "WORK_OVERDUE": {
        "meaning": "Reported work has exceeded its declared interval or timeout. This is evidence of missing progress, not proof of an unrecoverable process.",
        "next_read": "Report immediately with operation, last attempt/success and observation time. Use at most one follow-up read; do not loop or repair.",
    },
    "PROGRESS_EVIDENCE_STALE": {
        "meaning": "The agent has stopped publishing fresh work status. Its recorded task state may no longer describe the current situation.",
        "next_read": "Report the coverage gap immediately. Compare process/heartbeat and one permitted follow-up log read; do not infer successful work.",
    },
    "PROGRESS_EVIDENCE_UNAVAILABLE": {
        "meaning": "Current-process work metadata is unavailable, unreadable or invalid.",
        "next_read": "State the coverage limit. Do not treat an old process's status as current work or grant additional permissions.",
    },
    "HEARTBEAT_FAILURE": {
        "meaning": "A supervisor could not verify a child's heartbeat. Missing hello.moto can occur before first spawn; it does not prove a dead process.",
        "next_read": "Compare the affected child's current process and heartbeat evidence with the timestamp. Repeated failures without a recent/sleeping heartbeat need prompt operator attention.",
    },
    "PUNJI_DROPPED": {
        "meaning": "The supervisor logged a punji shutdown request after a failed heartbeat check while a matching process still existed. This is intervention evidence, not proof of exit or successful restart.",
        "next_read": "Report immediately when encountered, even if a later heartbeat is recent. Include affected child, reporting supervisor, timestamp and current observation. Recovery and application health remain unproven.",
    },
    "PUNJI_DROP_FAILED": {
        "meaning": "The supervisor logged failure to write a punji shutdown request; its intervention may be blocked.",
        "next_read": "Report immediately with the affected child and supervisor. Inspect permitted recent logs for access failures and repeated heartbeat failures.",
    },
    "UPSTREAM_QUOTA_EXHAUSTED": {
        "meaning": "A logged upstream request failed because credits or quota were exhausted; a live process does not establish that this function works.",
        "next_read": "Report the timestamp and evidence. Operator review of the upstream account is needed; do not request credentials.",
    },
    "PERMISSION_FAILURE": {
        "meaning": "A logged operation was denied access. This may affect one function while the agent continues heartbeating.",
        "next_read": "Report repeated failures promptly. Identify the denied function from safe evidence; do not widen permissions or repair automatically.",
    },
    "EXCEPTION": {
        "meaning": "A sampled log contains a Python exception. Process presence alone does not establish worker recovery.",
        "next_read": "Report repeated exceptions promptly, with first/last sampled timestamps and count. Read permitted logs for context.",
    },
    "DEPENDENCY_UNAVAILABLE": {
        "meaning": "A logged import failed. The process may keep running while a function cannot initialize.",
        "next_read": "Report repeated failures promptly even with a recent heartbeat. Identify the affected function from permitted evidence; do not install or change dependencies automatically.",
    },
    "LOG_WARNING": {
        "meaning": "A sampled log contains an application warning. Multiple warning records may describe different conditions, not one repeating fault.",
        "next_read": "Report repeated warnings for operator review even with a recent heartbeat. Use evidence to explain possible impact; do not declare an unrecoverable agent from the warning count alone.",
    },
    "LOG_ERROR": {
        "meaning": "A sampled log contains an application error; its current impact requires context.",
        "next_read": "Report repeated errors promptly. Repetitions within a bounded tail do not establish continuous failure or duration.",
    },
}


def lifecycle_subject(code, message):
    """Extract only from already-redacted messages in known supervisor formats."""
    patterns = {
        "HEARTBEAT_FAILURE": r"\[HEARTBEAT\] ([A-Za-z0-9_-]{1,128})(?::[A-Za-z0-9_.-]+)? failed(?:[: ]|$)",
        "PUNJI_DROPPED": r"\[BOOT\]\[PUNJI\] Dropped punji for ([A-Za-z0-9_-]{1,128})\s*$",
        "PUNJI_DROP_FAILED": r"\[BOOT\]\[PUNJI\]\[WARN\] Could not drop punji file for ([A-Za-z0-9_-]{1,128})\s*$",
    }
    pattern = patterns.get(code)
    match = re.match(pattern, message) if pattern else None
    return match[1] if match else None


def annotate(finding, reporting_id, inventory):
    """Recompute interpretation at the broker boundary; ignore supplied hints."""
    code = finding["code"]
    affected = finding.get("affected_agent_id") if code in LIFECYCLE_CODES else reporting_id
    current = inventory.get(affected)
    observation = ("not_in_inventory" if current is None else
                   "not_observed" if current["state"] == "not_observed" else
                   "unknown" if current["state"] == "unknown" else current["heartbeat"])
    immediate = (code in {"PUNJI_DROPPED", "PUNJI_DROP_FAILED", "UPSTREAM_QUOTA_EXHAUSTED",
                           "EXPECTED_AGENT_NOT_OBSERVED", "DUPLICATE_AGENT_PROCESSES", "STALE_HEARTBEAT",
                           "WORK_BLOCKED", "WORK_OVERDUE", "PROGRESS_EVIDENCE_STALE",
                           "THREAD_HEARTBEAT_STALE", "SPAWN_BURST"}
                 or (finding["occurrences"] > 1 and
                     (code in {"PERMISSION_FAILURE", "DEPENDENCY_UNAVAILABLE", "EXCEPTION", "LOG_ERROR", "LOG_WARNING"}
                      or (code == "HEARTBEAT_FAILURE" and observation not in {"recent", "sleeping"}))))
    return {**finding, "affected_agent_id": affected, "reporting_agent_id": reporting_id,
            "current_observation": observation, "report_immediately": immediate}


def finding_order(finding):
    return (finding["code"] not in {"PUNJI_DROPPED", "PUNJI_DROP_FAILED"},
            not finding["report_immediately"])


def report_hints(rows):
    codes = {finding["code"] for row in rows for finding in row["findings"]}
    return {
        "diagnostic_cards": {code: dict(CARDS[code]) for code in sorted(codes & CARDS.keys())},
        "priority_finding_count": sum(row["priority_findings_total"] for row in rows),
        "reporting_guidance": "Present report_immediately findings first, including historical punji events even after a recent heartbeat. Report as soon as this inspection returns; do not wait for another inspection. Present three layers for each affected agent: process/thread and spawn observations, work progress with last successful operation, and timestamped log findings. Counts group records by category, affected agent, operation and thread, not necessarily the same cause. Priority means prompt attention, not automatic critical severity. Work progress is self-reported for instrumented functions only; idle on-demand work is not a stall. Missing/stale records leave functional coverage incomplete. Working is not healthy; idle does not establish recovery from an earlier failure. A missing watch path may leave partial coverage. Unreadable logs do not distinguish missing configuration from missing paths or permission errors without supporting evidence. Follow up at most once per affected agent if needed, then report and stop. Read-only evidence grants no authority to spawn, restart or repair. This is a bounded snapshot, not continuous monitoring.",
    }
