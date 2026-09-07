# Harvester

Harvester is a server-side MatrixSwarm agent. It watches active universes
through the authoritative `matrixd list --json` process inventory. The first
release intentionally binds one Harvester instance to one universe through one
host in either `local` or `ssh` mode. A directive containing multiple targets
fails closed; multi-SSH fan-out is deferred until this single-link path has
passed live testing.

In SSH mode, Phoenix injects the selected deployment's Railgun SSH constraint
into the encrypted directive at `config.ssh`. The deployment picker copies only
the deployment identity, encrypted-directive filename, and SSH registry serial;
it does not read or copy the target swarm key. Harvester requires Railgun-style
SHA256 host-key pinning, disables ambient key discovery, and runs one fixed
remote `matrixd list --json` command. Connection material is never included in
Harvester alerts or logs. Local mode needs no SSH constraint.

Each target declares the minimum expected agent count. Consecutive failures and
recoveries are debounced before signed alerts are emitted. The shipped metadata
is disabled and has no targets.

This milestone is observation-only. Harvester has no boot command, recovery
switch, directive upload, target key, or caller-supplied command surface. Once a
single SSH-linked Harvester has proven that it detects a stopped swarm and
notifies the operator, recovery authority can be added as a separate phase.
