# Agent work evidence

`AgentProgress` publishes a small, atomic `progress.json` in the agent's current
runtime communication directory. It records useful work separately from process
presence and thread heartbeats. Publication failure leaves a diagnostic coverage
gap and must not break the measured work. Files are bound to agent ID, PID and
process start by the diagnostic reader; live Phoenix also binds reads to the
verified swarm boot.

## Instrument actual operations

Register a fixed operation name from `OPERATIONS`, its expected interval (or
`None` for on-demand work) and timeout. Add new names to both the core publisher
and Phoenix Terminal's independent `progress_diagnostics.py` validator. Install
both sides before interpreting new records.

```python
from core.python_core.agent_progress import AgentProgress

self.progress = AgentProgress(self, {"log_read": (30, 60)})

# At the place that actually reads the log:
with self.progress.attempt("log_read"):
    read_current_log()

# During the existing worker loop, without declaring successful work:
self.progress.flush()
```

An attempt records failure and re-raises exceptions. For code that catches
errors internally, use `begin`, collect fixed failure reasons, then call
`finish` explicitly. A rejected/no-op protocol request can `abandon` its token;
it proves neither success nor a storage failure. Heartbeat emission and reading
a progress file must never record successful work.

Separate independent functions into separate operations. A successful listener
poll does not clear watch setup, and an inbox listing does not clear a failed
commit. A success clears that operation's blocker only if the attempt started
after its most recent failure. `finish(..., clear_failure=False)` records a
successful selected subset without clearing an earlier aggregate failure.
Last-failure history is retained after success. Recovery is a self-report for
the operation, not a functional test of the whole agent or the same failed item.

## Bounded target context

For watch setup or file reads, collect observations while doing the actual work:

```python
from core.python_core.agent_progress import path_target

targets = [path_target("access_log", 1, configured_path,
                       "permission_denied", "PERMISSION_DENIED")]
self.progress.set_context("traffic_read", targets)
```

Target kinds, states and reasons are fixed enums. A label is an observation,
never a caller-supplied probe. `path_hint` permits only bounded service labels
under `/sites`, `/var/log`, `/var/www` or `/srv/www`; traversal, private/credential
components, key-file suffixes and unsupported characters become `None`. No
contents, raw exceptions, credentials, inbox IDs or configuration dumps belong
in this record. The server and client independently rebuild context fields.

Failures are ordered first. At most eight targets per operation and sixteen
per agent are exported; the serialized file is additionally capped at 16 KiB.
Trimming preserves `total_targets` and sets `truncated`. Counts refer to targets
observed during a build/collection, not proof of every expected target. Context
has its own observation time and can be older than the publication timestamp.
Indices refer to the current ordered configuration; compare permitted path
labels and boot identity where available, and report withheld labels as limits.

## Current instrumentation

| Agent | Operations | Meaning of success |
| --- | --- | --- |
| Oracle | `llm_chat`, `llm_embeddings`, `llm_clusters` | That upstream operation completed. Idle does not prove quota or auth recovery. |
| Log Health | `log_read` | Its actual configured log read completed. |
| Tripwire Lite | `watch_setup`, `event_listener`, `quarantine` | Watch build, listener poll and quarantine outcomes are independent. Setup can have partial coverage. |
| Site Sentinel | `site_checks`, `traffic_read` | A site-check cycle ran; site health is separate. Access logs actually opened/read; first pass starts at EOF. |
| Log Watcher | `collector_read` | A full configured file collection completed. Selected-subset success cannot clear an aggregate block. |
| Drop Vault | `inbox_setup`, `inbox_list/read/begin/chunk/commit/cancel/delete`, `inbox_cleanup`, `inbox_reply` | Per-operation outcomes. A queued reply is not delivery; success on another item is not proof of that item's recovery. |

The client derives `success_after_failure` only from fresh records with a cleared
blocker, a later success for that operation, and no overdue work. Stale/unavailable records remain
unverified. New processes have new histories; a reboot alone is not recovery
evidence. Existing read permissions, approval, expiry and revocation still apply.
No additional scans, repairs, file access authority or Linux permissions are
granted by instrumentation.
