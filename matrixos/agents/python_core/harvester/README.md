# Harvester

Harvester is a server-side MatrixSwarm agent. It watches active universes
through the authoritative `matrixd list --json` process inventory. The first
release intentionally binds one Harvester instance to one universe through one
SSH assignment. A directive containing multiple targets fails closed;
multi-SSH fan-out is deferred until this single-link path has passed live
testing.

Phoenix metadata declares `harvester_assignment` as a required registry-backed
constraint. Its editor pairs one vault deployment with one Registry SSH object
and an explicit authority: `contact_only` or `contact_and_resurrect`. The saved
Registry object contains references and policy, not copied credentials. During
directive compilation Phoenix resolves those references from the unlocked
vault and injects the selected SSH profile and one target into Harvester's
encrypted directive. Harvester requires Railgun-style SHA256 host-key pinning,
disables ambient key discovery, and runs one fixed remote `matrixd list --json`
command. Connection material is never included in Harvester alerts or logs.

Each target declares the minimum expected agent count. Consecutive failures and
recoveries are debounced before signed alerts are emitted. The shipped metadata
is disabled and has no targets.

`contact_only` is the safe default and never places the target swarm key in the
Harvester directive. `contact_and_resurrect` is an explicit capability grant;
only that selection injects the target's vault-held key, Linux user, and exact
encrypted-directive path. Recovery remains double-gated, bounded, and cooled
down. The key is delivered to the fixed boot process over SSH stdin and is not
written to a target key file or command line. Harvester never uploads a
directive, discovers a target, or runs a caller-supplied command.
