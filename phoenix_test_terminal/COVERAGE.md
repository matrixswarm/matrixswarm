# Phoenix process coverage ledger

Baseline: 2026-09-26. This is an evidence map, not a release certificate or code
coverage percentage. Counts overlap in setup. Passing mocks do not certify servers.

## Evidence levels

- **Untested:** no relevant automated behavioral evidence identified.
- **Simulated:** mocks, source assertions or injected responses verify a contract.
- **Local verified:** actual Qt controls/processes/crypto/files exercised offline.
- **Live verified:** observed real hardware/server workflow; needs a dated report
  identifying the exact source revision and environment to be release evidence.

Levels apply to individual checks, not whole features. For every workflow, check
success, Cancel, invalid input, failure/retry, persistence/restart and late callbacks.

## Current workflow map

| Workflow | Available evidence | Important remaining gap |
|---|---|---|
| Fresh vault create/unlock/reopen | Local verified: `run vault`; real encryption and fresh interpreters | Packaged cold start, OS dialogs, migrations |
| Password rotation | Local verified vault cycle; simulated write/busy failures and cancellation in `test_vault_rotation_guard.py` | Physical YubiKey and native window shutdown |
| SSH registry lifecycle | Local verified: `run registry-lifecycle` | Every registry class, real SSH onboarding |
| Workspace creation/assignment | Local verified: `run workspace-lifecycle` | Full palette/constraint combinations |
| Graph editing and saves | Local verified: `run graph-save`; injected disk failures | Native close/kill, crash recovery, long-running stress |
| Editor validation | Local verified selected controls: `run editor-validation`; injected unexpected exceptions | Every editor/schema, provider-specific semantics |
| Background vault queue | Real encrypted graph writer; simulated failure/close/late-callback cases | OS shutdown/power-loss and multi-process writers |
| SSH key install/export | Simulated regression adapters: `run ssh` | Disposable real SSH server matrix |
| Clown Car/directive launch | Simulated plus local source/hash checks: `run deployment` | Golden-swarm deployment; valid-but-wrong source selection |
| Railgun install | Mock transport/progress: `run railgun` | Clean-machine install/upgrade/failure/recovery |
| Custom panels | Selected protocol regressions: `run panels` | Every panel with live agents and delayed/disconnected replies |
| Alerts/Harvester | Simulated regressions: `run alerts`; user reported live transitions historically | Reproducible integration evidence tied to current revision |
| Packaged first-run to cockpit | Partial startup/routing evidence: `run startup` and `run vault` | Entire fresh-user journey in packaged application |
| Full source cockpit first-run | Local verified: `run cold-start`; clean create/unlock, workspace save, fresh-process reopen | Packaged executable, native file dialogs, visual checks |

Historical user-observed deployments are useful diagnostic evidence, but do not
replace current, reproducible live verification. No blanket live-certified row.

## Inventory baseline

`python -B -m phoenix_test_terminal inventory` statically discovers **139 candidate
surfaces**, of which **13 have explicit partial-behavioral mappings** at this baseline.
No parse errors or stale mappings were found. Other candidates can have unit/source
tests without a mapping. Conversely, one mapping does not cover all methods or paths.
Discovery is heuristic (including indirect BaseEditor subclasses), not exhaustive.

## Risk-ordered next work

### Final atomic-cleanup verification

Broad suite: 523 tests, no failures/errors, four Windows platform skips. All six
Railgun groups pass in `phoenix-cleanup-atomic-1.json`. Nine cleanup tests include
shared-lock recheck/persistence and busy-vault rejection. User supplied live log
at 20:32:27 confirms a fresh receipt and removal of two matching vault records,
with server files unchanged (before the subsequent lock tightening).
Detailed session/PR description: SESSION_RELEASE_NOTES.md at repository root.

### Session stopping point

Final broad unittest rerun: 514 tests, no failures/errors, four explicit platform
skips on Windows. Harness self-tests: 21 passed. Full process report
`phoenix-session-final-sweep-1.json`: 60 stages passed, deployment group failed
on stale source-layout assertions plus the known platform skips. Updated those
assertions for the background worker and bounded poller; targeted report
`phoenix-session-deployment-final-1.json` now has only the two POSIX/Linux skips.
The original failed report is preserved, not relabelled green.

Broad discovery also exposed unsupported os.getloadavg/statvfs on Windows in
the read-only Operator status reporter. Unsupported metrics now return None,
with a platform-unavailable regression. CI now installs the Qt test dependencies,
uses offscreen Qt, prints the Railgun report and explicitly runs trusted Linux
remote-launch tests outside the harness's subprocess guard. CI is configured,
NOT remotely verified. No commit, push or server change performed.

Remaining before release: actual Linux CI results; review commit scope and exclude
local report artifacts; revisit the success-only deployment cleanup option below.
Packaged fresh-user, physical hardware, power-loss and disposable live golden-swarm
coverage remain separate gaps; this session does not certify the entire product.

### Success-only deployment cleanup (implemented before commit)

User authorized a default-checked removal option. Cleanup matches exact universe
and normalized literal IP plus SSH port; different targets remain untouched.
Only unchanged records captured before launch are removed, and only after exit=0
and the matching fresh completion receipt. Historical replay, cancellation,
unknown targets/legacy records, changed records and newer concurrent deployments
are preserved. This deletes vault records, never server files. The original vault
must still be active; rejected writes are reported without mutating live state.
The updated server helper emits the fresh receipt: older helpers leave records
untouched until updated. Seven cleanup tests pass with all six Railgun groups in
`phoenix-cleanup-1.json`. No real vault records were deleted during testing.

### Durable Railgun request audit (2026-09-26)

Follow-up user log at 19:45:11 shows embedded Matrix source with SHA256 beginning
239c5f18, HASH OK and exit=0. This verifies that observed embedded-Matrix launch,
not every child agent or same-request receipt replay.

MatrixD Control polling/close audit: output draining is bounded to 16 chunks per
stream per Qt turn, including fair stderr processing and delayed closure until
buffers drain. Remote output is inserted as plain text. Escape/reject, done and
window-close release sessions; cleanup failures log safe locations and do not
skip the other resource. Six new offscreen lifecycle tests and all five Railgun
groups pass in `phoenix-control-lifecycle-2.json` (local Temp).

Follow-up: MatrixD Control now prepares SSH connections, capability probes,
command dispatch and envelope upload in ControlSessionWorker, not the GUI thread.
Session ownership transfers to the GUI poller only after worker completion.
Close/Escape request cancellation and defer destruction; users close again once
clear. Duplicate operations are blocked during preparation as well as streaming.
Late cancellation closes the prepared session rather than installing a poller;
post-dispatch cancellation reports unknown remote outcome, never rollback.
Ten control lifecycle tests pass, including held connect/probe/upload with live
Qt heartbeat, cancellation, late handoff and GUI-thread polling. All five Railgun
groups pass in `phoenix-control-worker-2.json` (local Temp). SSH is simulated;
live timing, DNS stalls and native OS forced termination remain unverified.

User confirmed a normal (non-Clown-Car) installation/deployment after updating
MatrixOS. Supplied log records clean prior-agent shutdown and new Matrix launch
with exit=0 at 19:40:39. Hash verification was explicitly skipped, as expected
without a supplied hash; this is not Clown Car or receipt-replay verification.

Retry Qt-boundary follow-up: malformed saved port, missing swarm key and launcher
exceptions now report a visible error with safe traceback locations, without
exception payloads/secrets. Active-operation retries are blocked. Thirteen receipt
tests (including three failure subcases) and all four Railgun groups pass in
`phoenix-retry-boundary-1.json` (local Temp). No live retry was performed.

`phoenix-durable-request-3.json` in local Temp passes all four Railgun groups.
Eleven new receipt/identity tests exercise completed replay, concurrent requests,
interrupted execution, changed-content rejection, incomplete input, rejected
vault persistence, and initial retry target matching. The actual receipt code
runs against temporary files with a mocked command executor; no live server or
power-loss durability certification is claimed.

Full rerun `phoenix-durable-full-sweep-1.json`: 59 stages passed, one stage failed
the completeness gate solely for the two existing POSIX/Linux skips. No assertion
failures. Deployment rerun `phoenix-durable-deployment-2.json` also verifies saved
initial options match dispatch. No WSL distribution was listed locally; Linux
checks remain outstanding. `git diff --check` passes (existing CRLF warnings only).

Updated Phoenix requires `matrixos/scripts/matrix-railgun-request` installed on
the server. Missing helper blocks before stopping the existing universe. Receipts
live in root-owned mode-0700 `/var/lib/matrixswarm-railgun`, with hashes/status only.
An interrupted request retains its per-universe `.active` lock and requires an
operator to reconcile actual server state before any recovery; never blindly
delete locks. A completed receipt is historical command outcome, NOT current
swarm health. Retry initial request preserves the saved target/options/identity;
intentional new boot/restart is a separate explicit choice.

Fresh Windows baseline (`run all`, 2026-09-26): **50 stages passed; one failed the
gate because two POSIX/Linux checks were skipped** in `test_remote_ssh_launch.py`
(POSIX shell rendering and Linux prctl memory protection). No other stage failed.
The aggregate is not green; those checks require Linux verification. Separately,
21 harness self-tests passed. Remote CI has not been run in this session.

1. **Packaged fresh-user journey:** clean profile, create vault, reach cockpit,
   create workspace, save, quit, relaunch and reopen. No inherited vault or settings.
   Source-cockpit version now passes locally via `cold-start`; this does not close
   the packaged-artifact gap. No packaging manifest/executable was identified in
   this checkout during this sweep.
2. **Shutdown/late-worker matrix:** close during each active worker, fail/retry,
   confirm no writes after cancellation and no deleted-widget access.
3. **Disposable golden swarm:** install, deploy, connect, observe, disconnect,
   recover and stop on explicitly authorized test infrastructure.
4. **Remaining registry/editor families:** expand behavioral mappings only after
   real control tests, not merely because their source imports successfully.

## Deferred user requests

- Clown Car source-root override implemented: deployment options show the last
  location and a Reselect MatrixOS Source picker. Explicit selection excludes old
  cached roots from discovery; complete verification replaces remembered roots.
  Tests decrypt the resulting bundle to verify new bytes, verify incomplete
  overrides prompt/cancel without old-source fallback, and exercise picker cancel.
  `phoenix-clown-source-override-1.json` in local Temp: Clown Car and local deployment
  tests pass; only the known POSIX/Linux skips block full deployment certification.
- Railgun cleanup implemented as described above; legacy entries without a saved
  literal IP target remain for explicit manual review.
- AUTOGEN: field-specific generation options, including relevant key/cert settings.

## Keeping evidence honest

### Additional cancellation and failure-boundary audit

- Connection-loss audit: synthetic disconnects during connect, command dispatch,
  upload, and missing exit status produce no automatic replay. SSH exit status -1
  now reports unknown remote outcome, not completed command. Workers are single-use
  even if restarted; no second connect/dispatch occurs on the same attempt.
  Seven stream/lifecycle tests pass, plus the complete Railgun group, in
  `phoenix-railgun-loss-1.json` (local Temp). This does NOT certify idempotency
  across newly constructed attempts or app restarts. The remote command builder
  can kill/restart the universe when reboot flags are supplied. Durable request
  identity and server-side duplicate suppression remain outstanding before that
  checklist item can be marked complete.

- Active sealed-stream cancellation: Railgun now offers Cancel local operation,
  guards Escape/done/window-close while its worker runs, and checks cancellation
  before dispatch, between bounded upload chunks, and while receiving output.
  Upload deadline is 60s; response deadline is 120s; channel opening is bounded.
  After remote command dispatch cancellation/failure reports unknown remote
  outcome, never claims rollback, and advises checking the universe before retry.
  Five synthetic-SSH/offscreen-Qt tests pass (early cancel, partial upload cancel,
  partial/zero sends, upload deadline, dialog lifecycle). Railgun suite passes;
  deployment retains only its two known platform skips. Reports in local Temp:
  `phoenix-upload-cancel-1.json`, `phoenix-upload-deployment-1.json`.
  No live cancellation test or duplicate-remote-launch certification is claimed.

- Sequential cancellation audit, preparation portion: mocked rejection of label,
  options, Clown Car source selection, and encryption preview causes no vault
  patch or launcher call. Rejected vault persistence now blocks launch and no
  longer mutates the live deployment dictionary before the patch. Successful
  preparation returns True for dispatch only; cancellation propagates False to
  DeploymentSession. Six preparation subcases and session propagation pass.
  `phoenix-preparation-cancel-1.json` in local Temp records the deployment rerun:
  Clown Car, isolation, fail-closed and cancellation groups pass; the remote-launch
  group remains incomplete solely due to the two platform skips. In-progress
  upload cancellation and remote retry behavior are NOT checked off.

- Required-component failure audit: invalid registry constraints, empty required
  bundles, missing required AUTOGEN editors, registry resolution exceptions, and
  injection failures now block preparation rather than allowing partial builds.
  Resolution operates on a staging tree, and each attempt resets its builder.
  Offline tests verify visible blocking, no mocked launch on four failure cases,
  preserved input, and one mocked launch after a corrected retry. Six compiler
  tests and two session tests pass, as do Clown Car and SSH groups. Deployment
  completeness remains blocked by the two platform skips. Reports in local Temp:
  `phoenix-failclosed-deployment-1.json`, `phoenix-failclosed-ssh-1.json`.
  Mid-upload cancellation and remote retry idempotency remain unverified.

- Deployment compiler isolation: reproduced input connection mutation on both
  successful and rejected compilation. Existing connection data and resolved
  constraint fields are now deep-copied before assembly. Two offline regressions
  verify input preservation and nested output isolation. This is not evidence
  that the earlier missing outgoing-route symptom had this cause.
- Follow-up compiler audit: public directive output now deep-copies both explicit
  editor fields and resolved fallback fields, and calls the field provider once.
  Each private compile starts with a fresh certificate map; failed attempts clear
  partial certificate state without changing previously returned results. Five
  compiler isolation tests pass (including four public-field subcases). Clown Car
  and all four SSH test groups pass; deployment remains incomplete on Windows
  because of the two previously recorded POSIX/Linux skips. Reports:
  `phoenix-compiler-retry-1.json` and `phoenix-compiler-retry-ssh-1.json` in local Temp.
- Matrix SSH: user supplied live logs showing ingress online and authenticated
  packet relay after the composed-control change. Source-hash verification was
  explicitly skipped in that deployment; do not count it as integrity-tested.

- Vault create/unlock: cancelled dialogs ignore late hardware callbacks; unlock
  rejects non-object decrypted data; create-path preparation failures are visible
  and logged without exception payloads. Eight rotation/cancellation unit tests
  pass. Fresh-vault and full source-cockpit suites pass again after these changes.
- Railgun recon: Escape, done, and window-close defer while its worker runs,
  request interruption, and never wait on the GUI thread. The user retries close
  after the bounded operation finishes. Unexpected check/cleanup exceptions are
  reported with safe diagnostic locations, not allowed to escape the worker.
  Regression tests use real Qt dialogs and synthetic SSH clients, not a server.
- User-reported lid/sleep shutdown was clean; forced termination durability is
  still not certified by that observation.
- Full offline rerun: `phoenix-autonomous-sweep-1.json` (local Temp report),
  53 stages passed and one deployment stage failed the completeness gate solely
  for two platform skips (POSIX shell rendering and Linux prctl). No assertion
  failures were reported. Harness self-tests: 21 passed. This remains partial
  coverage, not release certification or evidence of live deployment success.

Run reports with new filenames; preserve failures/skips and environment details.
Update this ledger with evidence, not estimates. `gate` deliberately remains blocked
by incomplete parity even when individual offline sections pass. CI now includes
editor-validation and rotation guards in addition to vault/workspace/graph suites;
remote CI execution has not been verified merely by editing the workflow.
