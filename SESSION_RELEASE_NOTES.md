# Phoenix reliability sweep, test terminal and safer Railgun deployment

## Summary

This change set strengthens Phoenix's first-run, persistence, editor, deployment,
and Qt worker boundaries. It adds a separate offline process-test terminal and
durable Railgun request receipts, restores explicit Clown Car source selection,
and adds success-only cleanup of previous matching deployment records.

The objective is to expose failures that an established developer vault or a
happy-path deployment can conceal. Tests deliberately exercise cancellation,
rejected writes, stale callbacks, missing prerequisites, and connection loss.
Passing this suite is not a claim of full GUI parity or release certification.

## Vault and workspace integrity

- Exercise creation, unlock, wrong-password/corrupt-input handling, persistence,
  rotation and reopening in fresh processes with disposable encrypted vaults.
- Serialize background workspace writes, retain accepted edits, and publish saved
  state only after successful persistence. Keep the GUI responsive during writes.
- Reject overlapping synchronous mutations while background writes are pending.
- Preserve live registry/workspace state when a transaction is rejected.
- Guard closed vaults and late dialog/hardware callbacks; prevent active-vault
  password rotation from racing accepted writes.
- Recheck deployment cleanup and persist it under one reentrant writer lock.
  The encrypted file writer flushes/fsyncs and atomically replaces its file;
  in-memory state advances only after persistence is acknowledged.

## Graph, registry and editors

- Repair autosave paths for graph reparenting, requirements and branch deletion.
- Preserve configuration/service metadata across editor saves and keep edited
  structures detached from caller-owned data until accepted.
- Restore the currently assigned registry selection when inspecting constraints.
- Validate malformed editor values instead of silently accepting defaults.
- Add safe exception-location diagnostics at audited GUI boundaries, without
  logging exception payloads or secrets.
- Separate generic SSH credentials from Matrix SSH agent configuration with a
  composed assignment editor/provider and SSH constraint output.
- Improve workspace refresh and close behavior around pending saves/callbacks.

## Deployment preparation and Clown Car

- Add an explicit MatrixOS source selector to deployment options, displaying the
  remembered location. A new explicit root does not silently fall back to an old
  checkout for missing agents.
- Validate every required embedded source, support correction/cancellation, and
  remember verified roots only after a complete successful selection.
- Isolate compiler inputs and per-attempt certificate maps. Required dependency,
  AUTOGEN, resolution and injection failures now block partial deployments.
- Persist a new deployment before dispatch; rejected persistence prevents launch.
- A preparation success means dispatch, not proven remote swarm health.

## Railgun responsiveness and retry safety

- Harden preparation/upload cancellation, single-attempt workers, timeout/error
  handling and deferred dialog destruction while workers are running.
- Move MatrixD Control connection, capability checks, command dispatch and sealed
  envelope upload off the GUI thread. Transfer session ownership only after worker
  completion. Block overlapping operations and handle late cancellation safely.
- Bound output draining per Qt turn and treat remote output as plain text in the
  control poller. Release both resources even if one cleanup step fails.
- Preserve host-key pinning and sealed SSH-stdin boot transport.
- Add the root-owned `matrix-railgun-request` helper with durable, hash/status-only
  receipts and a per-universe active lock. Complete input must arrive before the
  stop/provision/boot operation begins.
- Repeated completed requests return historical outcomes without repeating boot.
  Changed content under the same ID is rejected. Interrupted outcomes retain a
  lock and require operator reconciliation, not blind replay or lock deletion.
- Persist original request identity/options/target for an explicit initial retry.
  Intentional new boot/restart remains a separate choice.
- Missing helper fails before stopping the old universe. Updated MatrixOS must be
  installed before using this new path.

## Default-checked previous-deployment cleanup

- Deployment options default to removing previous matching vault records after
  successful fresh completion. Users can opt out.
- Require both exact universe and normalized literal target IP, with SSH port as
  an additional separation boundary. Same-name universes on other servers remain.
- Delete only unchanged records captured before launch. Keep the new deployment,
  later-created entries, edited records, and legacy records without a saved IP.
- Require exit=0 plus a fresh completion receipt matching this request. Historical
  replay, cancellation, failure and missing receipt never trigger cleanup.
- Require the original vault to remain active; recheck and write within one locked
  transaction. Busy/closed vaults or failed writes retain old records and report a
  cleanup warning without turning remote success into a false deployment failure.
- This removes vault records only, never server files or running universes.
  It does not archive the removed records; retain a vault backup if history matters.
- The updated helper emits the completion marker. Older helpers can finish a boot
  but will leave records untouched until updated. Fresh exit=0 proves command
  completion, not ongoing health of every child agent.

## Separate diagnostic test terminal and CI

- Add `phoenix_test_terminal`, separate from the production application, with
  per-section help, diagnostic contracts, machine-readable reports and an explicit
  coverage ledger. Use real offscreen Qt, encryption and disposable files where
  practical; mark simulated transports and untested behavior honestly.
- Guard test writes/network/subprocess access and reject skipped, empty, invalid,
  timed-out or failed results as full certification. Reports are not overwritten.
- Cover vault, cold start, graph, workspace, registry, editors, SSH, deployment,
  Railgun, panels, startup and alerts. These are partial mappings, not every dialog.
- Add Windows/Linux process CI and align security CI dependencies with Qt tests.
  Run trusted Linux shell/prctl checks on the disposable CI runner outside the
  test terminal's no-subprocess guard. Remote CI results remain to be observed.
- Update source-layout assertions for the new worker and bounded polling design.
- Make unsupported Operator status metrics return unavailable on Windows rather
  than raising missing-API errors; retain Linux behavior.

## Verification and known limits

- Harness self-tests: 21 passed during the session.
- All six Railgun groups pass, including cleanup scope, cancellation/replay gates,
  rejected persistence, and locked transform/persistence checks.
- Final broad suite: 523 tests, no failures/errors, four explicit Windows skips.
  Atomic cleanup checks verify the recheck and persistence share the writer lock.
- Full process sweep recorded 60 passing stages and a failing deployment group;
  stale source-layout assertions were repaired and the targeted rerun has only
  the two outstanding POSIX/Linux skips. Preserve the original failed report.
- User-supplied live logs show both normal and embedded-Matrix launches with
  exit=0, including an embedded Matrix HASH OK. Latest supplied log shows a fresh
  receipt and removal of two matching old vault records, server files unchanged.
- Remaining gaps: actual Linux CI results, packaged clean-machine first-run,
  physical hardware, power-loss durability, comprehensive live golden-swarm tests
  and complete editor/panel parity. No blanket production certification.
- No production server actions were performed by the automated local tests.

## Commit scope

Includes the session's source fixes, tests, harness, CI and this description.
Excludes the local `graph-save-repro.json` artifact. No credentials/private keys
or local vaults are intended for the commit. No push or PR mutation is included.
