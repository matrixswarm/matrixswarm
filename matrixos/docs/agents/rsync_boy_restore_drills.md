# RsyncBoy filesystem restore drills — first iteration

RsyncBoy 2.6.0 can schedule a filesystem restore drill independently of its
backup job. A backup finishing does not advance the drill's success record.
A drill copies one completed snapshot into a fresh private directory, checks it
against the inventory sealed during backup, and removes the scratch copy.
It never restores into a live source directory and never runs restored code.

This iteration is ready for operator validation. Automated and live acceptance
checks have not been run for this change.

## Scope

| Checked | Outside this iteration |
| --- | --- |
| SHA-256 of every regular file; file sizes and complete entry inventory | Starting applications, opening a site, or database import/recovery |
| Directory/file entry types, symlink targets, permission mode and whole-second modification time | ACLs, extended attributes, ownership and application-specific permissions |
| Restored regular files have independent inodes from the backup | Proving the original source was application-consistent during backup |
| Snapshot identity and backup job definition match | Independent/offsite signatures against a malicious backup administrator |
| Scratch cleanup and a durable private verification receipt | Historical snapshots without a sealed inventory |

Special files (sockets, devices and FIFOs) fail verification. Symlinks are copied
as links, never followed during verification. Hard links within the restored
tree are preserved by rsync, but their exact topology is not a verified claim.
The root directory is a scratch container; its metadata is not certified.
Every run hashes both the selected snapshot and the restored copy against the
creation-time baseline. A checksum generated only after restoration would not
detect corruption that already existed in the snapshot.

## Storage requirements

- Linux, Python 3.10 or newer, and rsync on the snapshot storage host. A push
  backup uses the existing pinned SSH profile; it also needs `python3` on that
  host. Pull backups run the drill on the MatrixOS backup host.
- Deploy the complete updated RsyncBoy source, including its filesystem helper
  modules, and restart through the ordinary operator workflow. Update Phoenix
  for the new job editor and report display. AI Mode remains read-only.
- Use a dedicated snapshot root for each filesystem backup job. It must be
  owned by the storage account and not writable by other accounts. Symlinked
  roots/ancestors and untrusted writable ancestors are rejected.
- Provision a separate restore root owned by the same account with mode `0700`.
  The helper can create it if the parent permissions permit. Never choose a
  source directory, snapshot directory, or an ancestor/descendant of either.
  A typical root is `/backup/restore-drills`.
- Leave room for an independent copy: the preflight checks logical file bytes
  plus the configured free-space reserve. Other processes can still consume
  disk space during the drill. Entry/byte/time limits are additional bounds,
  not a filesystem quota or a guarantee against competing writers.
- Treat completed snapshots as immutable, particularly when hard-link
  incrementals are enabled. Do not edit, chmod or chown completed snapshot
  files; an inode may be shared by multiple snapshots.

## Configure in Phoenix

1. Open the live RsyncBoy panel in Normal Mode. Edit a filesystem backup job
   and enable **Create SHA-256 Verification Inventory**. Save the schedule.
   Existing jobs retain disabled verification until explicitly enabled; new
   jobs in the editor default to enabled verification. Hashing adds I/O and is
   bounded to 250,000 entries, 1 TiB of logical
   file bytes and one hour during backup sealing. Larger jobs need a later
   capacity iteration. You can disable hashing on a backup that has no drill.
2. Execute that backup and confirm success. Old snapshots are not retrofitted.
   New snapshots contain `snapshot.manifest.json` schema 2 and
   `.rsync-boy.inventory.jsonl`; those two root-level names are reserved and
   cannot occur in the backed-up source tree.
3. Add a **Filesystem restore drill** job. Set its own job ID and select the
   filesystem backup's job ID. SSH selection is inherited from that backup.
4. Set **Completed Snapshot** to `latest` or an exact dated snapshot name.
   `latest` is resolved once under the retention lock. `.partial` directories
   and redirected/absolute latest links are rejected.
5. Set the private restore root and bounds. Defaults are one hour, 250,000
   entries, 100 GiB of logical file bytes and a 1 GiB free-space reserve.
6. For the first rehearsal, save the drill **disabled** and use **Execute Now**
   once after the new backup exists. Execute Now intentionally permits a
   disabled saved job. Enable its schedule after inspecting the result.
   For a weekly schedule use `interval_sec: 604800`.

Enabled jobs without a previous success are eligible on the next scheduler
pass, including when Run on Boot is unchecked. Failed drills use the existing
retry interval (normally 900 seconds). Execute Now does not retry itself.

## Example drill definition

Include this alongside a filesystem job named `sites_daily` in the same
schedule. The source job must have `verify_manifest: true`.

```json
{
  "id": "sites_weekly_restore",
  "enabled": false,
  "factory": "filesystem.restore_drill.RestoreDrillJob",
  "schedule": {"interval_sec": 604800, "run_on_boot": false},
  "config": {
    "backup_job_id": "sites_daily",
    "snapshot": "latest",
    "restore_root": "/backup/restore-drills",
    "timeout_sec": 3600,
    "max_entries": 250000,
    "max_bytes": 107374182400,
    "min_free_bytes": 1073741824
  }
}
```

Changing the backup's definition invalidates previous drill success for the
current configuration. Create a new backup before repeating the drill.
The encrypted scheduler records backup and drill successes under separate job
IDs. A failed drill leaves the prior successful timestamp unchanged.

## Read the result and hand it to another operator

The live panel distinguishes **VERIFIED**, **FAILED**, running and never-run
drills. Hover the drill's State cell for the selected snapshot, verified file
count and report location. The timestamp column is per job: the backup row
reports backup success; the drill row reports verified restore success.

Each attempt writes a private JSON receipt in the restore root. It contains
job IDs, exact snapshot name, start/finish timestamps, verification counts,
coverage and any fixed failure code. The latest copy is
`drill_JOB_ID.latest.json`; up to thirty separate attempt receipts are kept so
the previous successful result survives a later failure. The encrypted agent
ledger also retains the last successful drill timestamp across restarts.
Receipts and restored data remain on the snapshot storage host, including for
push backups; Phoenix does not fetch the restored data.

A drill holds the storage root's advisory retention lock throughout selection,
verification and copying. Updated RsyncBoy retention defers pruning
when that lock is busy, and always preserves `latest`. Every process that prunes
this root must use the updated helper; older binaries or external cleanup jobs
do not honor this advisory lock. A crashed helper releases the lock through
the operating system. A killed process can leave a private scratch directory;
inspect it before operator cleanup. It is never reused by the next drill.

Validation failures are explained in the private receipt's `detail` field.
Other fixed codes include `SNAPSHOT_BUSY`, `TIMEOUT`, `PERMISSION_DENIED`,
`MISSING_PATH` and `RESTORE_FAILED`. An unwritable or unsafe restore root may
prevent receipt creation; the live ledger still records a failed attempt.
Ordinary timeouts permit a twenty-second scratch cleanup grace period.
An unsuccessful cleanup is a failed drill and reports `cleanup_required` with
the generated scratch directory name.

For handoff, give the next engineer the backup job ID, snapshot location,
exact dated snapshot name, latest successful drill receipt and the intended
application recovery procedure. A VERIFIED receipt establishes the file
checks listed above; it does not certify that a website or database can start.

## Gemma observation prompt

> Use phoenix-term-ops. Request approval, connect once to the permitted current
> runtime and inspect once. Report RsyncBoy's timestamped RESTORE_DRILL evidence,
> exact job ID and selected snapshot when available. Separate backup completion
> from verified restore completion. State missing evidence and sampling limits.
> Do not execute a job, create a backup, restore data, boot, restart or repair
> anything. A heartbeat alone establishes no restore success. Stop on a failed
> required call, denial, expiry or revocation; do not poll or retry yourself.

This iteration exposes completion through the normal panel/ledger and agent
logs. It adds no AI write adapter or per-job progress projection. A sampled log
without a completion entry leaves the drill's outcome unverified for Gemma.
