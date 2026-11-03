# Global Alarm

**Status: Provisional — QC testing needed.**

Global Alarm schedules personal reminder messages and queues them to agents
advertising each reminder's alert service role. Alarms are managed in Phoenix and saved in the agent's
encrypted persistent state. Phoenix may be closed while the MatrixOS universe
continues running.

## Setup

1. Update Phoenix and MatrixOS from this source tree. The MatrixOS agent package
   must include both `global_alarm/global_alarm.py` and `global_alarm/engine.py`;
   embedding an entry point alone does not deploy the other module.
2. Add `global_alarm` in Swarm Workspace. Assign its packet-signing constraint
   and a **dedicated** `persistent_state` Registry record. Keep the record,
   state ID, key, and universe consistent across redeployments.
3. Include the normal Matrix command ingress and Phoenix `hive.rpc` callback
   path, plus configured `telegram_relay`, `discord_relay`, and/or `email_send`
   agents advertising `hive.alert`. Complete their credentials, destinations,
   and any desired alert-encryption settings. In each relay's agent config
   editor, use Service Manager Roles to advertise the role it should receive,
   such as `hive.alarm.telegram@cmd_send_alert_msg`.
4. Configure Global Alarm's default outgoing role in its agent config editor.
   Deploy, connect Phoenix, select Global Alarm, and open its panel. Each
   reminder can use the default or specify another role; omit the handler from
   the outgoing role, for example `hive.alarm.telegram`.

This change does not deploy a running server or configure actual recipients.
Authenticated Phoenix operators who can manage the agent share its alarms;
there are no per-user private alarm lists.

## Use

Enter a title, message, date and time, IANA time zone (for example
`America/New_York`), repeat setting, and alert service role. Use **Add /
Update Draft** to stage an item and **Save Changes** to commit the complete
list. Save also stages the current edited form. Select a row to edit it; use
**New** to start another, **Delete** to remove it, and **Reload Saved** to
refresh state. A successful save acknowledges encrypted
agent storage, not final message delivery. A changed form or new draft is shown
as unsaved until acknowledged. Conflicting saves from another panel are
rejected until reloaded.

The panel shows the agent host's time, current UTC offset, and system time
zone when available. It estimates seconds between refreshes and marks the
clock stale if it cannot obtain a fresh report. Alarm times continue to use
the IANA zone specified for each alarm, not the server's default zone. The
panel also refreshes saved alarm status while open without replacing unsaved
edits; a waiting role means no matching listener has been discovered.

Supported schedules are once, daily, and weekly. Repeats follow local wall time
in the chosen time zone. A start time in a daylight-saving gap is rejected;
future repeat occurrences in a gap are skipped. For a repeated local time during
a fall-back transition, the first occurrence is used. The runtime needs IANA
time zone data (`tzdata` is included in MatrixOS requirements).

If the agent was stopped at the scheduled time, it queues the missed reminder
when it resumes. Missed recurring occurrences are coalesced into one reminder,
then scheduling continues at the next future occurrence. Disabled alarms do not
fire; enabling an overdue alarm can queue it immediately.

## Delivery and limits

Matching listeners are discovered when an alarm becomes due. If none are
available, the alarm remains pending and discovery is retried. Once listeners
are found, their IDs are saved with the occurrence and each is queued
independently. If a packet cannot be queued, that target remains pending and
is retried; already queued targets are normally not sent again. A queued packet is a
handoff to the relay, **not confirmation that Telegram, Discord, or SMTP
actually delivered it**. Relays may be disabled, misconfigured, or fail after
handoff. Runtime status is refreshed while the panel is open; if the connection
is interrupted, reload or reconnect to confirm the latest state.

The scheduler records state around handoff, but a crash or storage failure after
queuing and before the success record is saved can cause a duplicate on retry.
Exactly-once delivery and downstream delivery receipts are not implemented.
Changing the schedule re-arms an alarm. Editing a pending message or its
recipients keeps the occurrence pending for any destinations not yet queued.
Existing alarms saved with explicit relay IDs retain those targets when edited;
the panel offers an explicit option to convert each one to service-role routing.

Message privacy after relay handoff depends on the relay's configuration and
the external service. The 200-alarm maximum, 2,000-character message limit,
32-destination maximum for older explicit-target alarms, and polling interval
bound resource usage.

## Tests

Run `python -B -m unittest discover -s tests -p 'test_global_alarm*.py' -v`
from the repository root. Panel tests require PyQt6 and can run with
`QT_QPA_PLATFORM=offscreen`.
