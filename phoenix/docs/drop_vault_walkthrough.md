# Drop Vault: a traveling clipboard

Paste text or drop a file in Phoenix on one computer, then retrieve it from
another Phoenix connected to the same live `drop_vault` agent. The agent keeps
both content and metadata encrypted while they wait. Delete an item from either
Phoenix when finished. This feature is independent of Phoenix Terminal; the
Terminal work is parked and no Terminal permission was added.

## Prepare once

1. Run Phoenix from this updated source tree on both computers. A Python virtual
   environment elsewhere is fine, but an older Phoenix checkout will not contain
   this new palette entry or panel.
2. Install/update MatrixOS from this source tree so the remote agent package
   includes **both** `drop_vault/drop_vault.py` and `drop_vault/store.py`. This
   change does not update or deploy any live server automatically.
3. In Registry, create a **new dedicated `persistent_state` record**, as with
   Crypto Alert. Do not reuse Crypto Alert's record. Assign the new record to the
   `persistent_state` constraint on the new `drop_vault` workspace agent.
4. Keep its packet-signing constraint and generated service-manager role intact.
   Deploy it in a swarm with the normal Phoenix command ingress and `hive.rpc`
   callback relay. All connected, authenticated Phoenix operators for that swarm
   share this inbox; there are no per-item private user accounts.
5. Connect, select the agent, and open **Drop Vault**. The initial listing loads
   automatically. The same record, state identity, key and universe must be kept
   on redeployment to retrieve existing drops. Keep the key securely backed up.

## Daily use

- **Paste:** enter optional title/notes, type or drag selected browser text anywhere
  inside the Paste tab, or use **Paste from clipboard** at its upper right. Nothing
  is sent until you click **Upload Text**. A successful acknowledgement clears only the submitted draft;
  newer text you typed during the upload is retained.
- **Drop files:** set optional title/notes first, then drop regular local files
  onto the drop area or use **Choose files**. Up to 16 files are queued in order.
  Local file reads, hashing and exports run off the GUI thread.
- The list loads on opening, optionally polls every **60 seconds**, and offers
  **Check now / Latest** plus **Older** paging. Up/down buttons move selection.
  Polling pauses during a transfer and when the panel is hidden.
- Selecting text retrieves it and displays it as **plain text**, never HTML.
  **Copy text** copies it to the local clipboard. The optional 60-second clear
  affects only the clipboard value still owned by this copy, not later copies.
- Selecting a file retrieves it into memory and verifies its SHA-256 checksum.
  **Save copy** exports it to a location you choose. **Copy file** first asks
  where to save that local file, then puts a file reference on the clipboard.
  **Drag saved copy** drags that explicitly exported file to another application.
  The panel creates no hidden plaintext download cache and never executes files.
- **Delete from agent** confirms before removing the shared entry and encrypted
  object. Other instances observe the deletion on their next check. It cannot
  revoke bytes already downloaded, copied, exported or backed up elsewhere.

## Storage and failure contract

The existing Registry-provisioned `persistent_state` key is used through
`EncryptedStateMixin` (HKDF-separated, authenticated AES-256-GCM). There is no
new hardcoded key, key file or plaintext database.

SQLite runs **in memory**. After a catalogue change, a SQLite-generated SQL
snapshot is encrypted and atomically replaces `catalog.json.aes`. This portable
format works on Python versions without SQLite `serialize`; it is not SQLCipher
and is not a plaintext `.sqlite` file. SQL values are inserted with parameters.
Timestamps, type, optional title/notes, original filename, byte size, SHA-256 and
opaque object ID are stored in the catalogue. The ID addresses the separate
`objects/<id>.json.aes` content envelope; original filenames are never server paths.

The directory is beneath:

```
/matrix/universes/static/<universe>/persistent/<state_id>/drop_vault/
```

An OS-level exclusive writer lock prevents two agent processes from opening the
same store simultaneously. Uploads use bounded memory buffers and 8 KiB chunks;
no plaintext upload spool is written. The object is durably encrypted first,
then the catalogue is published, then success is acknowledged. Repeating the
same upload chunk/commit after a lost response does not duplicate an entry.

A crash between object write and catalogue publication can leave an **encrypted,
unlisted orphan**. It is not automatically published or blindly purged. Incomplete
in-memory uploads disappear on restart or after five idle minutes. If a request
times out, use Check now before retrying: a missing acknowledgement is not proof
that a commit failed. Cancel during commit likewise does not guarantee rollback.

Deletion publishes a durable removal receipt before deleting the content file.
If the content unlink fails, the item is unavailable through the agent, but the
encrypted file remains until background cleanup succeeds. This is ordinary file
deletion, not a promise of physical secure erasure or backup removal.

Bounds: **1 MiB/object** (including UTF-8 pasted text), **256 MiB / 1000 items**, four concurrent uploads, two
short-lived decrypted read-cache objects, 20 catalogue entries/page. Text fields
are also bounded by their JSON-escaped representation to fit packet guards.
This is for small files and pastes, not bulk transfers. The logical object limit
is not a packet limit: a full-size item uses 128 sequential 8 KiB data chunks,
plus begin/commit requests and acknowledgements. Existing perimeter limits stay
unchanged (128 KiB packet, 96 KiB content, 32 KiB per string); signed/encrypted
envelopes must fit those limits too.
Unexpected storage errors report type and stack locations, not object contents.
Corrupt storage or an incorrect key fails closed; it is never replaced by an
empty inbox. There is no key-rotation migration in this version.

## Security boundary

Requests require a verified Matrix identity and the exact target agent. Replies
are session/token/request scoped through the existing encrypted callback path.
There is no arbitrary path, URL fetch, shell, auto-open or generic file-manager
operation. This is a shared operator clipboard, not an LLM Terminal capability.

Encryption protects stored objects, not an unlocked client/server or its admin.
Clipboard history/sync, local exports, screenshots, swap/crash dumps and backups
need their own protection. Deleting an item does not recall those copies.
Do not use real sensitive information for the first test.

## Acceptance test with two computers

1. In Phoenix A, paste `Drop Vault test only` with a title and note; upload it.
2. In Phoenix B, connect to the **same agent/universe**, open Drop Vault, and
   select the item. Confirm timestamp, notes, content and Copy text.
3. Drop a small harmless file in A. In B, Check now, select it, Save copy, and
   compare the file bytes. Try Copy file/paste into Explorer and Drag saved copy.
4. Delete the text in B. Check now in A; it should disappear. Delete the file
   from the agent too; the explicitly exported local copy should remain.
5. Leave a harmless item on the server, restart/redeploy with the **same**
   persistent-state assignment, and verify it returns. Then delete it.

If **Check now** remains on “Checking encrypted inbox,” inspect the logs for
that attempt. With the updated MatrixOS, Matrix reports **Routed** only when
its packet delivery succeeds; otherwise it reports **Delivery failed**. The
Drop Vault agent reports that it accepted a `list` request, or gives a reason
for rejecting its sender/routing fields. A failed callback logs that the session
reply was not queued. A successful reply is restricted to the live Phoenix
`session_id`; it is never fanned out to other sessions. Use harmless text until
the updated MatrixOS is installed, since older Matrix service logs may print
the entire request payload.

Automated synthetic tests (from the repository root, PowerShell):

```powershell
$phoenixPy = 'C:\Users\pete\PycharmProjects\phoenix_gui\.venv\Scripts\python.exe'
$env:QT_QPA_PLATFORM = 'offscreen'
& $phoenixPy -B -m unittest discover -s tests -p 'test_drop_vault*.py' -v
```

These tests cover real Qt panels, agent handlers, encrypted persistence and
packet budgets in-process. They do not substitute for a live two-computer test
or certify native Explorer drag/drop behavior on every desktop platform.
