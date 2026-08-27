# MCP SDK worker

The worker is the only MatrixSwarm component that imports the MCP Python SDK.
It receives a deployment-approved MCP command and a reduced tool allowlist but
no MatrixSwarm package, identity object, or private key.

Railgun installs these requirements into `/matrix/mcp/.venv`; they are never
added to the MatrixOS environment or `matrixos/requirements.txt`.

At universe deployment time Railgun creates two identities:

- the universe service account, which runs Matrix and native agents;
- a distinct MCP worker account, which owns only its private working directory.

The universe account may invoke exactly one argument-free sudo command:
`/usr/local/libexec/matrix-mcp-launch`. The root-owned launcher loads a
root-owned profile, verifies the worker hash, applies resource limits and
`no_new_privs`, drops supplementary groups/GID/UID, and then executes this
worker. The caller cannot select a username, interpreter, script, or command.

The process boundary is a dependency and capability boundary, not a statement
about the licensing of a deployment. Consult MatrixSwarm licensing terms for
that question.

V1 opens an MCP client session per request. This keeps the first read-only
smoke test and recovery model simple; a reuse pool can follow after the audit
path is proven.
