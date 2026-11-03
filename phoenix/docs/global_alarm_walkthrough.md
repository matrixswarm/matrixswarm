# Global Alarm: reminders to your swarm relays

1. Update Phoenix and the MatrixOS agent package, including `global_alarm.py`
   and `engine.py`.
2. Add **Global Alarm** to your workspace, assign packet signing and a dedicated
   persistent-state record, and deploy it with the normal Phoenix callback path
   and at least one configured Telegram, Discord, or email alert relay. Use
   the relay's Service Manager Roles editor to set the alert roles it listens for.
3. Connect, select the agent, and open **Global Alarm**. Enter a title, message,
   local date and time, IANA time zone, recurrence, and the alert service role
   to receive the alarm, for example `hive.alert`.
4. Click **Add / Update Draft** and **Save Changes**. You can also save directly
   after editing the form. Select an existing row to edit or delete it, and save
   again. The panel shows the server clock and refreshes saved alarm status
   while connected. Unsaved edits are labeled until acknowledged.

The agent queues reminders even with Phoenix closed, provided MatrixOS is
running. Queueing does not confirm external delivery. Check relay configuration
and send a test reminder before relying on an alarm. See the
[MatrixOS agent reference](../../matrixos/docs/agents/global_alarm.md) for
restart behavior, daylight-saving rules, privacy, and delivery limitations.
