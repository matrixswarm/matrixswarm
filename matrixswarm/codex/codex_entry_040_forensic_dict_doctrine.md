# Codex Entry 040: Forensic Dict Doctrine

*Ratified by the MatrixSwarm, July 2025*

---

## Article I: The Immutable Constitution of the Forensic Dict

Every incident, event, or forensic record committed to the Swarm must obey the following foundational law.  
Deviation is forbidden; omission is heresy.

---

### Section 1: Required Fields

A valid `forensic_dict` **MUST** contain:

- `incident_id`  
  *(str)*  
  Globally unique identifier for this incident.

- `incident_time`  
  *(str, ISO8601)*  
  UTC timestamp (ISO8601) when the incident was first observed.

- `source_agent`  
  *(str)*  
  The agent or system that first reported or synthesized this incident.

- `service_name`  
  *(str)*  
  The service, application, or component involved (e.g. "nginx", "mysql", "system.disk").

- `status`  
  *(str)*  
  Incident status at the time of record ("DOWN", "RECOVERED", "DEGRADED", "INFO").

- `severity`  
  *(str)*  
  One of: ["INFO", "WARNING", "CRITICAL", "FATAL"]

- `details`  
  *(str)*  
  Freeform summary of what happened and why this was recorded.

- `metrics`  
  *(dict)*  
  Structured supporting data (logs, error codes, stats).

---

### Section 2: Lawful Extensions

A `forensic_dict` **MAY** also include:

- `correlated_events`  
  *(list of dict)*  
  Linked events. Each event dict should include:  
  `event_hash`, `service_name`, `status`, `details`, `severity`, `count`, `first_seen`, `last_seen`, and any agent-specific fields.

- `full_forensic_report`  
  *(str)*  
  Markdown or plaintext human-readable summary including root cause and supporting evidence.

- `actions_taken`  
  *(list of str)*  
  Chronological list of actions performed ("auto-restarted", "alerted NOC", etc).

- `related_incident_id`  
  *(str)*  
  Links to related incident records (e.g. the RECOVERED event closing a DOWN).

- `agent_version`  
  *(str)*  
  Version or hash of the agent code that generated this record.

- `hostname`  
  *(str)*  
  System hostname or FQDN for forensic context.

- `tags`  
  *(list of str)*  
  Arbitrary keywords for search or filtering ("cloud", "PCI", "prod", etc).

---

### Section 3: Spirit of the Law

- Do **not** use flat arrays or custom blobs where a structured dict will suffice.
- Always prefer explicit, parseable fields over magic text in `details`.
- All times are **ISO8601** or UNIX epoch (document which is used).
- Never omit required fields—even if you must put `"unknown"`.

---

## Example: Forensic Dict (Incident Record)

```json
{
  "incident_id": "b1d7-11ee-99c0-fa163edb6be7",
  "incident_time": "2025-07-03T18:05:55Z",
  "source_agent": "nginx-sentinel-1",
  "service_name": "nginx",
  "status": "DOWN",
  "severity": "CRITICAL",
  "details": "Nginx process not running; all health checks failed.",
  "metrics": {
    "systemd_status": "...",
    "error_log": "...",
    "port_checks": { "80": false, "443": false }
  },
  "correlated_events": [
    {
      "event_hash": "d52cc...",
      "service_name": "system.disk",
      "status": "low_space",
      "details": "Root disk is 98% full",
      "severity": "WARNING",
      "count": 2,
      "first_seen": 1751555005,
      "last_seen": 1751555127
    }
  ],
  "full_forensic_report": "**Concise Analysis:**\n---\nProbable cause: Disk nearly full at time of nginx crash.\n---",
  "actions_taken": [
    "Attempted systemctl restart nginx",
    "Sent alert to NOC"
  ],
  "related_incident_id": "b1d7-11ee-99c0-fa163edb6be7:RECOVERED",
  "agent_version": "v1.5.7",
  "hostname": "web01.us-east.prod.local",
  "tags": ["prod", "public", "ssl"]
}

Amendment: The Law for Correlated Events
Any "event" object referenced in correlated_events must itself include
at minimum:

event_hash (str)

service_name (str)

status (str)

severity (str)

details (str)

count, first_seen, last_seen (if available)

Why This Doctrine Exists
Forensic records must be parseable and extensible for dashboards, bots, and postmortems.

New fields are welcome; old systems must tolerate unknowns.

Human-friendly for root cause, robot-friendly for data mining.

Enforced by the Swarm and the Forensic Chain of Trust.

End of Law

