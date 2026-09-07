# Harvester

Harvester is a server-side MatrixSwarm agent. It watches active universes
through the authoritative `matrixd list --json` process inventory. The first
release intentionally binds one Harvester instance to one universe through one
host in either `local` or `ssh` mode. A directive containing multiple targets
fails closed; multi-SSH fan-out is deferred until this single-link path has
passed live testing.

Phoenix metadata declares SSH as a required registry-backed constraint. The
operator assigns an existing SSH object from the encrypted Registry/Vault in
the Requirements panel; Phoenix injects it into the encrypted directive at
`config.ssh`. The Harvester editor never creates, removes, or edits that
constraint. Its deployment picker copies only the deployment identity and
encrypted-directive filename; it does not read or copy the target swarm key.
Harvester requires Railgun-style SHA256 host-key pinning, disables ambient key
discovery, and runs one fixed remote `matrixd list --json` command. Connection
material is never included in Harvester alerts or logs.

Each target declares the minimum expected agent count. Consecutive failures and
recoveries are debounced before signed alerts are emitted. The shipped metadata
is disabled and has no targets.

This milestone is observation-only. Harvester has no boot command, recovery
switch, directive upload, target key, or caller-supplied command surface. Once a
single SSH-linked Harvester has proven that it detects a stopped swarm and
notifies the operator, recovery authority can be added as a separate phase.
