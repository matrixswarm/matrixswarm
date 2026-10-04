# drop_vault

An encrypted shared traveling clipboard for authenticated Phoenix operators.
Upload text/files from one Phoenix and retrieve or delete them from another.
No remote shell, arbitrary path access, URL downloading or execution is offered.

Assign a **dedicated Registry `persistent_state` profile**, like Crypto Alert.
The key, state ID and universe must remain unchanged across redeployments.
The agent refuses to start without that assignment, and refuses a second writer
for the same store. Normal packet signing and a `hive.rpc` callback relay are
required. Service: `hive.drop_vault.request@cmd_request`; panel:
`drop_vault.drop_vault`. The agent package includes `drop_vault.py` and `store.py`.

SQLite metadata lives in memory; its SQL snapshot and each separate object are
authenticated/encrypted through EncryptedStateMixin. State is under
`universes/static/<universe>/persistent/<state_id>/drop_vault/`. There is no
plaintext SQLite journal or upload spool. Limits are 1 MiB/object, 256 MiB and
1000 entries, four uploads at once. Pending uploads expire after five idle
minutes or restart. Stored content is never executed.
This is a small-file/paste clipboard. Objects travel in 8 KiB chunks; the
existing perimeter packet limits are not raised.

Protocol operations are `list`, `begin`, `chunk`, `commit`, `read`, `cancel`, and
`delete`, each with exact validated parameters. Upload ownership is bound to the
request's session and panel token. Every authorized operator in the swarm can
list, retrieve and delete committed entries; these are shared, not user-private.

Objects are encrypted before catalogue publication; interrupted commits can
leave encrypted unlisted orphans. Deletion records a durable cleanup receipt and
retries failed unlinks. Keys/content are not included in the agent's diagnostics.
Wrong keys/corruption fail closed without erasing state. Keep backups of both
encrypted state and its key; no rotation/migration is provided here.

The Phoenix walkthrough is `phoenix/docs/drop_vault_walkthrough.md` in the
monorepo. Run `python -B -m unittest discover -s tests -p 'test_drop_vault*.py' -v`
from its root with the Phoenix test dependencies and offscreen Qt installed.
