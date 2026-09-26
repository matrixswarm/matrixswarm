# Phoenix Test Terminal

See [the coverage ledger](COVERAGE.md) for evidence levels, workflow gaps and
risk-ordered next steps. Test counts are not a code-coverage percentage.

`python -B -m phoenix_test_terminal run cold-start --report cold-start-report.json`
imports the complete source cockpit and boot wiring in a disposable profile,
checks locked/Cancel states, creates/unlocks a vault through real modal controls,
creates/saves a workspace, then reopens it in a fresh cockpit interpreter. File
pickers and message boxes are simulated; workspace controls are driven directly.
This is not packaged-binary, native-window-manager or hardware verification.

The full cockpit adapter also closes the vault through its control panel, cancels
reopening, injects a runtime-initialization failure, and retries. It reproduced a
logged-only failure after successful decryption: Phoenix remained locked without
an error dialog. The unlock boundary now reports failure visibly without raw
exception contents. Tests verify locked/disabled state, unchanged ciphertext,
visible diagnostics, and a functioning cockpit after retry.

Ordinary cockpit shutdown now rejects Close before stopping monitoring when a
vault write is active/queued, a visible workspace is unsaved, or a Qt child thread
is running. A visible message asks the user to resolve the work and close again;
it does not wait synchronously or silently discard edits. Full-cockpit tests hold
a real encrypted writer, exercise an unsaved graph and a held Qt worker, then
verify successful shutdown after resolution. Explicit security shutdown retains
its previous policy; forced OS termination and untracked/external workers are not
certified by these checks.

A **separate offline process-test laboratory**, not the production `phoenix_terminal`
bridge and not an LLM operating a user's GUI session. No production imports point
here. The lab imports the actual Phoenix code under test; it does not copy the
business logic into an alternate implementation that could drift.

## Status: partial coverage, not full Phoenix parity

Twelve diagnostic sections currently orchestrate existing regression suites plus a
new real-dialog, encrypted-vault lifecycle. `inventory` discovers dialog, widget,
panel and worker candidates and lists their methods. Most still need explicit
behavioral adapters. Static discovery is heuristic: dynamic factories, indirect
inheritance and non-class processes require human review too.

**A green section is not a release certification.** `gate` deliberately returns 2
while the documented coverage gaps remain, even when all implemented tests pass.
There is no ignore-skips or force-green switch. This initial implementation does
not claim to test every dialog/process, boot the packaged cockpit, or provision a
golden swarm. Those are visible release blockers, not silently assumed coverage.

## Run from the repository root

Use a dedicated virtual environment with Python 3.12+:

```powershell
python -m venv .venv-phoenix-test
.\.venv-phoenix-test\Scripts\python.exe -m pip install -r phoenix_test_terminal/requirements.txt
.\.venv-phoenix-test\Scripts\python.exe -m phoenix_test_terminal help
.\.venv-phoenix-test\Scripts\python.exe -m phoenix_test_terminal help vault --json
.\.venv-phoenix-test\Scripts\python.exe -m phoenix_test_terminal inventory
.\.venv-phoenix-test\Scripts\python.exe -m phoenix_test_terminal run vault --report vault-report.json
.\.venv-phoenix-test\Scripts\python.exe -m phoenix_test_terminal run all --report all-report.json
.\.venv-phoenix-test\Scripts\python.exe -m phoenix_test_terminal gate --report gate-report.json
```

Linux uses `.venv-phoenix-test/bin/python`. Reports must use a new filename.
Exit 0 means the selected adapters passed; 1 means failure, skip or zero tests;
2 means the full-coverage gate is not satisfied (or CLI usage is invalid).
Each worker has a configurable 1–600 second deadline, default 120 seconds.
The startup-policy adapter's nested interpreter has a separate 20 second limit.

The lab does **not** install Git hooks, commit, push or change repository branch
protection. A separate CI workflow checks harness invariants, fresh-vault lifecycle,
guarded startup and registry lifecycle on Windows and Linux. That job is explicitly partial coverage,
not the full release gate. Run `gate` before public commits/releases; wiring a
mandatory full release gate should happen once the listed parity gaps are covered.

## AI operator procedure

1. Read `help SECTION --json`: purpose, exact suites, expectations, diagnostic
   guidance and limitations. No arbitrary RPC, real vault path or shell command
   is accepted by the CLI.
2. Run the named scenario and inspect the JSON report's `results`, `errors`,
   `skipped`, `checks`, `elapsed_sec` and bounded `log`.
3. Reproduce the smallest failed section. Separate an app defect from a missing
   dependency, platform-specific skip, guard denial or coverage gap.
4. Diagnose the real handler/service/event boundary. Never fix a test by swapping
   out the behavior it was supposed to exercise or suppressing an assertion.
5. Add an error/cancel/restart test, then rerun that section and all adapters.
6. Check `inventory` and release gaps. Do not report comprehensive certification
   simply because a subset passed.

## Test vault and isolation

The fixture is created from scratch through **VaultCreateDialog's button signal**.
The only synthetic information is the test password and registry profile pointing
to `server.example.invalid`. Encryption, runtime store initialization, EventBus
save wiring and disk persistence are the production implementations. File pickers
and notification boxes are mocked to prevent modal interaction.

Seven separate interpreters perform create → opening failure paths/options →
cockpit unlock routing → initialize/persist → reopen → rotate → reopen/verify old
password rejection. Opening includes missing/empty/corrupt files, wrong-password
retry, picker/dialog cancellation, all session options, and simulated YubiKey
success/failure/cancellation through the real Qt worker. Routing executes the exact
AST-extracted `PhoenixCockpit.unlock_vault` method with real modal Qt dialogs driven
by timer/button signals; it does not import the application's unrelated top-level
launch side effects or instantiate the complete cockpit. It verifies create/unlock,
change/unlock, cancellation and runtime-failure policy reset. Physical hardware and
the final rendered cockpit still require separate validation.

A fresh interpreter prevents an
existing singleton or old vault from concealing a first-run failure. The new
vault has no registry data until the real create operation has succeeded. Failed
prerequisites block dependent stages instead of generating misleading passes.

Each section gets an automatically deleted temporary directory. HOME, USERPROFILE,
application data, temporary files and MatrixSwarm paths point there. Tokens,
SSH-agent environment and Python path overrides are not inherited. The live
terminal and GUI are not launched or connected. Source bytecode writes are off.

Python audit guards reject filesystem writes outside that directory, non-loopback
network operations, external DNS, and arbitrary child processes. The startup
policy adapter allows only its dedicated guarded Python child. Loopback is allowed
for local test doubles; it is not permission to query a running production bridge.

These are defense-in-depth controls for **trusted repository tests**, not an OS
sandbox: native libraries, reads, malicious tests, or preexisting local services
are not comprehensively isolated. Run untrusted changes in a disposable machine
with no credentials and OS-level network restrictions. Never put real secrets in
test fixtures; diagnostic logs are retained verbatim, bounded to 100 KB per worker.
Reports can contain synthetic keys and paths, so review before publishing.

## Extending coverage

- Register explicit suites and diagnostic contracts in `catalog.py`.
- Add adapters for real GUI handler signals and real service/store boundaries;
  mock external transports, not the state transition being tested.
- Track happy paths, invalid input, cancel, timeout, retry and restart persistence.
- The inventory's `partial-behavioral` tag means an adapter exists, not that all
  methods were exercised. Never infer coverage merely from filenames/imports.
- Remote boot/install, process-tree termination and hardware need dedicated
  disposable integration environments. Do not relax offline guards to run them.

Self-tests: `python -m unittest discover -s phoenix_test_terminal/tests -v`.

## Registry lifecycle (newcomer workflow, second slice)

`python -m phoenix_test_terminal run registry-lifecycle --report registry-report.json`

Creates a disposable encrypted vault, drives the actual RegistryManager Add/Edit
buttons and BaseEditor modal OK/Cancel validation, then reloads the profile in
fresh processes. It checks stable serial identity, metadata, encrypted credentials,
cancel-without-mutation, and the downstream SSH profile loader. Negative scenarios
exercise required fields, port bounds, host-pin format and rejected commits.

The initial run exposed production defects: blank username, ports 0/65536 and a
malformed host pin were accepted and persisted; rejected Add/Edit/Delete commits
left runtime mutations despite an unchanged vault file. The regression assertions
now protect the fixes: strict editor validation and staged namespace commits with
rollback on rejection or exception. Valid port boundaries and padded/unpadded
SHA256 fingerprints remain accepted. No live server or personal vault is involved.
False returns and exceptions are injected at the store boundary; normal persistence
uses the real store, EventBus and encryption code. This does not certify durable
transaction handling for asynchronous vault-writer failures, which is a separate
integration boundary.

## Workspace lifecycle (third slice)

`python -m phoenix_test_terminal run workspace-lifecycle --report workspace-report.json`

Creates a vault and registry profile using the preceding real adapters, creates
and renames a workspace through its manager, loads the actual graph editor, assigns
an SSH profile through the requirement row's registry picker, saves the graph, and
verifies the assignment after an interpreter restart. The unassigned SSH requirement
is a seeded fixture; inspector Add Requirement and remote deployment are not covered.

Rejected-save scenarios invoke the exact manager slots directly so an uncaught Qt
callback exception is recorded rather than aborting the test interpreter. The first
run exposed live-state mutation on rejected Clone/Rename/Delete saves and broken
WorkspaceStore reads (`root_vault` is absent; the base store uses `root`). Rename
also let its rejected-save exception escape its GUI slot. These regressions now
pass after staged manager edits, rollback/resynchronization, contained GUI errors,
and corrected WorkspaceStore CRUD. Both false returns and exceptions are injected;
the displayed list, live vault and encrypted file must remain unchanged. Store unit
tests additionally cover update/delete rollback, validation and detached reads.
As with registry tests, asynchronous writer durability is not certified here.

## Graph save/close failure probes

`python -m phoenix_test_terminal run graph-save --report graph-save-report.json`

Uses a fresh encrypted vault and real graph editor. A pending label edit is saved
with VaultCore.patch returning False or raising an exception, through both Save
and closeEvent. Each probe compares live vault data and encrypted bytes, requires
a visible error, and requires failed Close to reject its QCloseEvent. The pending
edit must remain available and persist on a successful retry. No personal vault,
network, or real deployment is used. This calls closeEvent directly rather than
driving a native window manager; asynchronous writer failures remain out of scope.

The original failures are repaired with detached snapshots, a serialized
background graph writer, Qt-thread completion handling and a bottom status bar.
Probes now inject queue-submission errors, worker errors and failure of the actual
atomic disk replacement. Retry uses the real button. A deliberately held writer
checks GUI heartbeats, newer-edit preservation, pending-close behavior and final
reload. No timed-out writer is abandoned to overwrite newer data.

Graph saves are asynchronous; legacy non-graph patch callers remain synchronous
and reject writes while a graph transaction is active. This does not claim that
every vault caller has been migrated to the background API. Slow graph writes show
an explicit request to pause edits after five seconds without freezing the GUI or
claiming success. Successful writes show "Saved to Vault" for three seconds, then
return to "Ready…". New writes cancel that reset; failure status stays visible.

Graph mutation probes run in a fresh worker after the save/close probes, with
explicit Qt widget/application teardown before interpreter shutdown, including
on assertion failure. They cover reparent autosave/reload, no-op/cyclic reparent
rejection, ID rotation/cancel/reference persistence, requirement removal, and
context-menu branch deletion/cancel. The missing requirement/deletion autosaves
are repaired and these regressions now pass. Real inspector-row picker tests
also verify current-profile preselection by serial, duplicate labels, cancellation,
missing serials and persisted reassignment without closing the editor.
The configuration-editor slice exercises actual agent double-click handlers,
modal Save/Cancel buttons, Harvester reopen, HTTPS routing preservation, and the
generic editor's scalar-type preservation. The generic editor now retains scalar
types and validates all fields before mutation. Invalid boolean/numeric/null edits
are rejected without partial changes; null fields cannot gain a type implicitly.
HTTPS, WebSocket and SSH editors now preserve routing/auth metadata and secondary
service entries when updating roles. The next sibling batch covers those editors
and Telegram, including Cancel. These regressions pass with real encrypted saves.
Other configuration editors and the full registry-assignment UI matrix still
need additional behavioral coverage.

The expanded service-role sweep reproduced metadata loss on Save in
cdn_dozer, matrix_email, meta_blast, oracle, sora, storm_crow, trend_scout,
tripwire_lite, uptime_sentinel and wordpress_plugin_guard. All tested Cancel
paths pass; email_send, discord_relay and apache_watchdog preserve the fixture's
service entries. Those ten editors now update roles through the shared preserving
helper. Add/remove/cancel role-list tests cover five representative editors, and
a missing-section Cancel probe caught and now protects WordPress editor defaults
from mutating live configuration before Save.
matrix_email_egress has an editor but no matching agents_meta file in this checkout
and is not exercised by this palette-metadata-based scenario.

## Editor validation

`python -m phoenix_test_terminal run editor-validation --report editor-validation.json`

Uses real Sora/Oracle widgets and synthetic configuration values. Empty/nonnumeric
duration and polling fields originally raised ValueError. The repaired handlers
are now exercised through actual Save buttons: they show validation warnings,
retain all config unchanged, and allow a corrected retry. Saved model names,
Sora resolutions and Oracle response modes absent from current presets are
retained in dropdowns and on Save. Preservation does not certify provider support.
No API requests or model-availability claims.

The numeric round-trip probes additionally seed Oracle temperature 0.125 and
Harvester interval/timeout values just above the UI limits (3601/301 seconds).
Oracle now displays additional precision and preserves the original numeric value
until edited. Harvester retains its runtime limits but visibly rejects invalid
imported numbers instead of saving clamped replacements. Validation precedes all
configuration mutations. Cancel preserves all three original values.

The next numeric batch covers nulls, malformed strings, objects, lists, booleans,
negative values, missing fields and corrected retries in these three fields.
Invalid persisted values open without modifying configuration and require correction
before Save; missing fields receive defaults only on Save, not Cancel. This is
numeric-field coverage, not a claim that every malformed configuration is handled.
Latest local runs: editor-validation 101 checks, graph-save 142 checks, and
20 harness self-tests passed. Full release readiness remains uncertified.

The dropdown/service-metadata batch reproduced constructor exceptions for invalid
dropdown types and malformed role lists, silent replacement of malformed service
entries, string roles splitting into characters, and default-role insertion into
explicitly empty Oracle role lists. Oracle/Sora now require an explicit valid
dropdown replacement before Save. Shared role rendering safely disables editing
with a visible warning for malformed service metadata and preserves it verbatim;
this does not validate or repair the imported runtime configuration. Explicitly
empty service/role lists remain empty, while defaults apply only to missing sections.
Sora uses the shared role renderer instead of its duplicated parser.

Latest expanded runs: 215 editor-validation checks, 142 graph-save checks and
20 harness self-tests passed. Coverage includes malformed secondary entries,
Cancel, untouched Save, and dropdown correction/retry; it is not full editor parity.

The text/checkbox batch reproduced constructor TypeErrors for non-string text/path
fields, null text silently becoming blank, and malformed booleans silently turning
into enabled/disabled settings. Sora watermark/output fields and Harvester alert
role/enabled fields now reject malformed persisted types before any Save mutation.
Invalid text uses a replacement prompt; invalid booleans display an indeterminate
checkbox until explicitly set. Cancel preserves original data and corrected retries
save normally. Valid strings (including Unicode paths) and actual booleans round-trip.
This validates field types, not remote path existence or alert-role availability.
Latest runs: 333 editor-validation checks, 142 graph-save checks, 20 harness tests
passed. No real vault or server was used; full release readiness is not certified.

Editor exception boundaries now report unexpected constructor/import/Save failures,
restore configuration and dirty state, and log exception types plus stack file,
line and function locations without raw exception payloads or local variables.
Broken imports no longer silently select the generic editor; fallback is limited
to a genuinely missing custom-editor module. Graph painting tolerates malformed
UI/agent_tree metadata without rewriting it. Fault injection covers partial-save
rollback, retry, constructor mutation, import failures and redacted diagnostics.
Latest validation: 347 checks passed; graph-save 142 and harness tests 20 passed.
Python exception handling is not native Qt/process crash capture.

Qt writer boundary probes verify queued completion delivery on the GUI thread,
rejection of off-thread save requests before queue mutation, and queue continuation
after a consumer callback raises. Completion callbacks now have safe diagnostic
logging and cannot unwind through the Qt signal handler. Disk-write success remains
distinct from UI-notification failure. The callback-failure queue test uses a mocked
writer; graph-save separately exercises the real encrypted background writer.
Latest runs: 353 validation checks, 142 graph-save checks, 20 harness tests passed.

Late callback tests now delete a real Qt workspace and close/switch its vault
before delivering a captured completion. Workspaces retain their owning vault;
stale dialogs cannot save into a newly opened vault. Deleted dialogs ignore late
UI updates. Vault replacement is rejected while writes are pending; already queued
writes retain the original vault target and closed cores suppress update broadcasts.

Deferred Railgun request: offer "Delete previous deployments" during universe
deployment, scoped to the target server identity AND universe name. Same-named
universes on different servers must never be grouped for deletion. No deletion
feature or remote cleanup is implemented in this test batch.

Queue-close fault injection confirms accepted writes drain to their original vault,
failure of the first write does not prevent the second, closed cores emit no UI
update broadcasts, and only successful writes update committed in-memory state.
Invalid workspace identities are rejected before queuing (missing IDs previously
raised KeyError; empty IDs were accepted). The queue also rejects noncallable
callbacks and malformed workspace sections. This fault injection uses a mocked
writer, supplemented by the real encrypted graph-save suite.

Clown Car now exposes an explicit source-root override so a valid but outdated
saved source tree can be replaced without making it disappear first.
User identified a wrong local source tree as the redeployment discrepancy; the
SSH hardening is not evidence of that incident's root cause.

Railgun retry testing (`run railgun`) includes durable server receipts. Updated
Phoenix requires the new MatrixOS `scripts/matrix-railgun-request` helper; install
the updated MatrixOS source before using the new deployment path. A missing
helper blocks before stopping the old universe. Use **Retry initial Railgun
request** for a lost initial acknowledgement, preserving its original identity
and options. Completed receipts return the recorded outcome without another boot;
they do not prove present health. Interrupted requests remain blocked pending
operator inspection. Do not delete receipt locks blindly. Explicit new operations
are separate from retries. Tests use disposable receipt files and fake execution,
not a live SSH server. See COVERAGE.md for remaining checks and the mandatory
success-only, same-universe/same-target cleanup. Deployment options now default to
removing previous matching vault records after fresh successful boot completion.
Opt out to retain them. Other IPs/ports/universes, records edited during launch,
and legacy records lacking a saved target identity are preserved. This does not
delete remote files. The updated MatrixOS helper must emit a fresh completion
receipt; an old helper or replayed receipt never triggers cleanup.

Password rotation audit: both password-change dialogs now route through the vault
service. Rotation of the same active or draining vault is refused before disk I/O;
the user must close it and let accepted writes finish. Failed decryption (non-dict
result) cannot be encrypted back over the original vault. The primary dialog reports
a busy vault distinctly from bad credentials. Targeted guard tests use mocks, while
the vault scenario exercises real encrypted rotation and fresh-process reopening.

Rotation-dialog fault injection additionally checks cancellation before late
YubiKey callbacks, disk-write error classification, no false success and corrected
retry. Cancel clears pending credentials; late ready/failure signals do nothing.
Unexpected exceptions report their type and safe stack locations rather than
always blaming credentials. Five rotation guard/dialog tests and 88 vault lifecycle
checks pass. Hardware callbacks are simulated; no physical YubiKey test is claimed.
