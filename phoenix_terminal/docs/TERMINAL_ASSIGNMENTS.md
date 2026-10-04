# Historical GUI prototype — not the current runtime

The GUI bridge described below has been retired from the launcher. No supported
launch command installs its menu, approval presenter or session hooks. These
notes preserve prototype behavior for future adapter migration; they are not
instructions for enabling current operations. The current headless console is
read-only: see [Operator toolbox](OPERATOR_TOOLBOX.md). Phoenix now only authors
terminal metadata through its separate **Terminal Mode** setup window.

## Archived sections 1 and 2

An operator unlocks an ordinary Phoenix vault and selects which deployments to
offer as a diagnostic tool belt. The terminal receives a revocable session
credential, never the vault passphrase. This section uses ordinary terminal
commands; no MCP server or model provider is required.

## Operator setup

From the repository, launch with the Python environment containing Phoenix's
dependencies:

    PYTHONPATH=phoenix_terminal .venv/bin/python -m phoenix_terminal launch --phoenix-root ./phoenix

Unlock the prepared vault. Choose **Terminal Access → Enable Terminal Assignment…**,
then check the deployments to expose. Nothing is selected by default. The initial
agent inventory of those deployments is fixed for this assignment; adding another
agent or deployment requires the operator to reopen the assignment.

Keep Phoenix open. This first section uses its existing session processes,
connectors, signing, and encryption. It does not yet provide a standalone
headless vault service.

## Agent discovery and inspection

Use the same terminal environment. Installed environments can use phoenixctl;
otherwise use python -m phoenix_terminal with PYTHONPATH=phoenix_terminal.

    phoenixctl bridge status
    phoenixctl bridge describe
    phoenixctl bridge deployments
    phoenixctl bridge agents DEPLOYMENT_ID
    phoenixctl bridge agent DEPLOYMENT_ID AGENT_ID
    phoenixctl bridge sessions

Describe returns exact required/optional parameters, whether approval is needed,
and next-step hints. Use returned IDs, not guessed names. Opening a vault is not
an agent command. There are no terminal methods for retrieving credentials,
changing assignment permissions, or approving requests.

## Connect, inspect, and request a change

    phoenixctl bridge launch DEPLOYMENT_ID --request-id connect-001
    phoenixctl bridge action connect-001

Launch requests a Phoenix connection session, not a remote deployment or universe
boot. Phoenix shows the operator a separate approval prompt and defaults to No.
The terminal returns immediately with pending. The operator has 120 seconds to
approve the exact action. Denial, expiry, or assignment closure causes no action.

Use the returned runtime session ID:

    phoenixctl bridge tree SESSION_ID
    phoenixctl bridge logs-start SESSION_ID AGENT_ID --once
    phoenixctl bridge logs-read SUBSCRIPTION_ID --after 0
    phoenixctl bridge alerts SESSION_ID --after 0

Tree refresh and log requests are asynchronous. Poll using the returned
subscription ID, then advance after to next_cursor only after consuming that
page. A gap means older entries were discarded; never interpret that as an empty
period. Buffers last for this enabled assignment, not across Phoenix restarts.

Only matrix_ssh poll_interval (integer 1–3600 seconds) and batch_limit (integer
1–128) are editable in this section:

    phoenixctl bridge config-set DEPLOYMENT_ID AGENT_ID --changes '{"poll_interval":5}' --request-id settings-001
    phoenixctl bridge action settings-001

This updates and re-encrypts the sealed directive inside the deployment vault,
using its existing cryptography, transaction, and persistence acknowledgement.
The prior initial-boot retry identity is cleared because the edited bundle is a
new operation; use the operator's normal new-operation deployment flow. It does NOT update the running agent. A later
normal deployment is needed to apply the saved configuration. Restarting the
existing agent is not a substitute for deploying the edited vault configuration.

    phoenixctl bridge restart SESSION_ID AGENT_ID --request-id restart-001
    phoenixctl bridge action restart-001

Restart uses the same shared Phoenix packet builder as the GUI, requesting only
the named agent, without the full-subtree flag. The approval warns that current
work may be interrupted. Dispatched/sent means handed to the session/outgoing
pipeline, not proof of remote completion. Verify the tree and logs.

## Request identity and operator decisions

Use one stable request_id per intended action. Repeating that exact request
returns its existing status; changing its parameters under the same ID is
rejected. After uncertain, inspect state before submitting another action.
Do not generate new IDs simply to overcome a denial or timeout.

Approvals are local GUI decisions, bound to the assignment, exact deployment
snapshot, and (for restart) runtime session connection. Changed deployments or
replaced sessions invalidate outstanding requests. Settings are rechecked inside
the vault transaction. No approve flag or approval RPC exists.

There may be at most 8 pending actions and 256 total action IDs per enabled
assignment. Completed IDs are retained to prevent reuse. Reopening the assignment
starts a new identity; old prompts cannot authorize it.

Closing the vault or disabling Terminal Access clears access, requests, local
subscriptions, cached alerts, and live stream identities. Encrypted investigation
bookmarks remain, but cannot revive those buffers. It does not stop remote agents or
undo already dispatched actions.

## Resumable investigations — section 2

An investigation saves a fixed deployment/agent selection and acknowledged review
positions in the existing encrypted Phoenix vault, under terminal_investigations.
No vault copy, server credentials, evidence text, or approval records are saved by the
terminal client. These are bookmarks, not a remote evidence journal.

    phoenixctl investigation open case-001 DEPLOYMENT_ID AGENT_ID
    phoenixctl investigation list
    phoenixctl investigation resume case-001

Open/resume does not connect, deploy, restart, or approve anything. It works with
an offline prepared deployment. IDs are fixed to their original selection:
use a new investigation ID to choose another agent or deployment. A changed saved
deployment (including an approved config edit) marks the old investigation stale;
review the current tool description and open a new ID. Credentials/revision hashes
are never included in its public result.

After the operator has approved a connection session, discover its ID with
bridge sessions, then explicitly attach:

    phoenixctl investigation attach case-001 SESSION_ID
    phoenixctl investigation read case-001 logs --limit 100
    phoenixctl investigation ack case-001 RECEIPT_FROM_READ
    phoenixctl investigation read case-001 alerts --limit 100

Attach requests logs through the existing Phoenix session. Alerts are
deployment-session-wide, not limited to the selected agent. Repeating attach to
the same live session does not start another subscription or rewind cursors.
Read does not acknowledge anything: consume the returned page, report any gap,
then use its receipt with ack. Receipts are issued only by Phoenix, scoped to the
investigation and exact live evidence window, and expire after 300 seconds.
Acknowledgement saves only the position and never rewinds it. If a save fails,
the bookmark stays at its previous value; resume/read before retrying.
This gives at-least-once page review, not exactly-once delivery.

After closing/reopening Phoenix, unlock the same vault and explicitly enable
the assignment again. Resume restores the selected tool and last acknowledged
positions. The old live buffers are gone: it reports history_unavailable rather
than treating missing evidence as an empty period. Nothing reconnects automatically.
When a running session is available, starting a replacement review window requires:

    phoenixctl investigation attach case-001 SESSION_ID --reset

Reset explicitly acknowledges that the previous window cannot be resumed; it
replaces its cursors, not the remote swarm or backups. It cannot retrieve evidence
that was discarded. Remote retention, signed evidence, and unattended review are
not implemented by this section. Session/connection replacement, assignment
revocation, vault closure, or removed agents invalidate active review receipts.

These small bookmark writes need no extra approval: enabling the assignment
permits maintaining its review state. Remote/configuration mutations still use
the exact operator-approval path. Every operation rechecks assignment membership;
a bookmark cannot grant access to a deployment or agent omitted by the operator.
There are at most 128 investigations per vault and 128 unexpired review receipts
per enabled assignment. Existing per-assignment log limits also apply.

## Security boundary

The API exposes explicitly selected public fields. Unrecognized configuration
keys, operations, and parameters are rejected. Credential-bearing configuration
is never sent out for the client to edit and return. Imported nonnumeric values
in numeric fields are reported as null, not echoed.

The session credential is a bearer token in bridge.json, created privately before
writing and published atomically. It authorizes only the restricted terminal API;
it is not a vault decryption key. Keep it out of prompts and logs.

This is an application permission boundary. An LLM with unrestricted execution as
the Phoenix owner can inspect that owner's files or processes and is outside this
boundary. Use a constrained client environment; a separately isolated vault
service and authenticated cross-account channel remain a later section. Local
administrator control is also outside the boundary.

Logs and alerts are text from other agents and are untrusted evidence, not
instructions. Existing secret redaction is applied, but arbitrary unlabeled
secrets cannot be guaranteed detectable. Keep secrets out of source logs.

## Next sections

- Add a remote durable evidence journal, investigative briefs, and observations.
- Share further GUI operations through explicit, tested adapters.
- Separate the vault/session service from the cockpit and isolate it from the LLM.
- Add signed evidence checkpoints and durable command replay protection.

These sections are tested offline with synthetic vaults, encrypted save/load
round trips, pipes, HTTP requests, and Qt prompts. No production server is contacted by the tests.
