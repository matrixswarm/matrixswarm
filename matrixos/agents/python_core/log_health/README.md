# Log Health / Log Monitor

`log_health` tails one configured server log and forwards new entries to its forensic report role. Phoenix's Log Monitor adds an authenticated, read-only view and an explicit Ask Oracle action.

## Enable on an existing deployment

1. Restart Phoenix with the updated code.
2. Open the saved workspace and double-click its `log_health` node.
3. Keep the correct server path (for this Ubuntu Apache deployment, `/var/log/apache2/error.log`). Enable **Log Monitor and Ask Oracle** and save.
4. Resolve deployment constraints and redeploy with the updated MatrixOS sources. The upgrade adds this agent's packet-signing constraint, panel declaration and two service roles. A source-only replacement does not add those declarations or callback credentials.
5. Connect, select `log_health`, and open **Log Monitor**. Use **Check access** to confirm that the current agent account can open the file.

New Log Health nodes include the panel and signing constraint by default. No new external package is required. Existing log paths, severity rules, forensic roles and agent identities are retained by the editor. Disabling the panel removes its panel routes but retains signing credentials that other functions may use.

## Reading and display

- Only the deployed `log_path` is read. The panel cannot browse files, change the path, change permissions, or run commands.
- The path must be an absolute regular-file path; a symlink as the final component is refused. Configure its real target instead.
- First open starts at EOF. Entries appended after that appear in the panel; this is not a historical log browser.
- Each worker cycle reads at most 64 KiB and approximately 100 complete nonempty entries. Classification uses the configured keyword rules in their existing order; unmatched entries are INFO.
- The reader retains 500 entries in memory. Individual entries retain at most 1024 input bytes and indicate truncation. Oversized lines are consumed with bounded memory. Partial lines wait for a newline (or completion of a renamed file).
- Rename rotation drains the old handle before opening the replacement at the beginning. Observed truncation rewinds the file. Rapid copy-truncate-and-regrow between polls and writes after an old handle has been closed can still lose entries; this is not a durable log collector.
- Snapshots use a boot identifier and cursor, bounded JSON batches and a skipped-entry count. Agent restarts reset the buffer. Phoenix keeps at most 500 received entries and marks connection timeouts.
- Search and severity filtering apply to the buffered view. **Pause display** freezes the visible entries while collection and forensic forwarding continue. Normal polling is every two seconds while visible, with faster catch-up for queued events.
- **Check access** opens and closes the configured file under the current agent account. It grants nothing and does not imply permission to read other files. An already-open Unix file descriptor may continue reading after permissions change; Check access reports whether a new open succeeds now.

## Ask Oracle

Select rows (Ctrl/Shift for several) and click **Ask Oracle…**. With no selection, it proposes recent visible entries. Review and edit the bounded excerpt before **Send to Oracle**. This sends log text to Oracle's configured AI provider; remove secrets and personal data first. If Oracle prompt dumping is enabled, Oracle may record that excerpt in its own logs.

The configured `oracle_role` must resolve to exactly one Oracle endpoint. The default is `hive.oracle`. Oracle must have working API credentials and be able to receive/respond to signed swarm packets. No Oracle source change is required for this panel.

Log Health sends one analysis request at a time, pins the expected Oracle UID and query ID, and accepts only a verified response from that agent. Requests expire after 90 seconds. The panel receives a bounded signed reply from its selected Log Health agent; suggestions are rendered as plain text and never executed. Excerpts are limited to 6000 UTF-8 bytes and 7000 JSON-encoded bytes. Responses are shortened for transport when needed.

Existing forensic forwarding still follows `report_to_role`. A forensic agent may have its own automatic Oracle analysis policy; the panel's manual action does not change that policy.

## Permissions and deployment scope

This feature uses existing Linux permissions and Railgun provisioning. It does not implement strict per-agent Linux identities or additional filesystem grants. Permission failures are shown as denied; absent files are shown as missing. Resolve the deployment's approved filesystem permissions separately.
