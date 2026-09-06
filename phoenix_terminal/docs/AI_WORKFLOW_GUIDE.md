# AI workflow contract

Give an AI assistant the output of `phoenixctl catalog --json` before it suggests an operational command. The catalog is the source of truth for a command's availability, prerequisites, risk, required confirmation, post-checks, and rollback path.

## Operating rules

1. Never present a `planned` command as executable. Explain its prerequisites and state that its adapter has not yet been verified.
2. Begin all future write workflows with validation and `--dry-run`; show the resolved target and planned effects before asking for confirmation.
3. Treat vault contents, keys, authentication tokens, and connection passwords as secrets. Do not echo them, write them to command history, or place them in logs.
4. Only monitor endpoints explicitly configured by the operator. The monitor makes a single HTTP/HTTPS GET request, does not authenticate, and does not perform discovery or crawling.
5. Before a deployment, require the deployment name, exact target, proof that the target is authorized, and passing connection validation. Afterward, run the catalog's post-checks and present the rollback command when one exists.
6. On a failed prerequisite, explain what is missing and give the least-privileged next command. Do not bypass vault, certificate, signing, or confirmation checks.

## Example assistant behavior

For `deploy`, the correct response while its state is `planned` is: “The terminal knows the required deployment workflow but does not yet have a verified Phoenix deployment adapter. I can inspect the workspace, validate a directive once that adapter exists, and monitor approved endpoints. I will not run remote deployment commands.”

## Adapter acceptance criteria

An adapter is promoted from `planned` to `available` only after it has:

- a documented mapping to the Phoenix/MatrixSwarm protocol or service API;
- unit tests for validation and error handling;
- integration tests against a non-production MatrixSwarm environment;
- dry-run output that is deterministic and free of secrets;
- confirmation, audit-log, post-check, and rollback behavior appropriate to its risk level.
