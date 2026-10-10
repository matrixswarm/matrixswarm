# Matrix SSH egress

`matrix_ssh_egress` returns RPC callbacks and alerts from the swarm to Phoenix.
Pair it with `matrix_ssh` for an SSH command and reply path. The workstation
initiates both SSH connections; it does not need an inbound listener.

## Configure

1. Install the updated MatrixOS source, including `matrix_ssh` and
   `matrix_ssh_egress`, and reopen the updated Phoenix application.
2. In Registry, add a `matrix_ssh_egress` route. Select an existing SSH
   credential, with its trusted server fingerprint, and select **Primary
   Incoming Transport** if this is the desired receive path. Credentials stay
   in the encrypted Phoenix deployment; they are not injected into the agent.
3. Add `matrix_ssh_egress` to the workspace and assign that route through its
   requirement. Use the separate `matrix_ssh` route for outgoing commands.
4. Deploy through the normal operator workflow and connect in Normal Mode.
   Phoenix starts the selected primary receiver automatically. Routes can
   switch the incoming transport later. If multiple routes are marked primary,
   the last in deployment order wins in startup, the dispatcher and Routes.
   Without an explicit primary, Phoenix prefers WebSocket, then the first
   receive route.
5. Observe the incoming badge, then request an agent status or log stream.
   A signed ready frame establishes the receive path; receiving an actual
   callback establishes application-level delivery for that request.

An operator run on 2026-10-09 booted `matrix-ssh-egress-378b84` at 18:55:35
America/New_York and recorded authenticated transport controls through
19:04:25. That establishes boot and control-inbox activity; the supplied log
alone does not establish every callback or alert delivery. AI Mode retains
its existing transport restrictions; this addition does not relax its
approvals or introduce an automatic SSH fallback.

A later operator run the same day confirmed SSH for both command ingress and
reply egress. At 19:41:50 America/New_York, Phoenix displayed a populated agent
tree and live agent logs, with SSH egress connected and Matrix SSH reporting
authenticated packet relays. This supplies live command and callback evidence;
automated acceptance and remaining failure scenarios have not been run.

## Perimeter panel

Select the agent in the live Phoenix tree and open **Matrix SSH Egress**.
The panel uses the existing signed service-request and verified callback paths:

- **Refresh Status** requests `matrix_ssh_egress.status`.
- **Open / Lockdown** and a duration control the reply perimeter. The default
  duration is 60 seconds; zero means indefinite and requires confirmation.
- **SSH egress agents** addresses all instances advertising
  `matrix_ssh_egress.toggle_perimeter`. **Perimeter marked agents** uses
  `hive.toggle_perimeter` and can also affect other transports.

Lockdown pauses new replies, alerts and SSH session controls. Existing spool
files still expire normally; queued replies may be collected by an already
connected receiver. The SSH server and the separate Matrix SSH command ingress
remain available when only egress is locked. Reopen through the command
transport, or wait for the timer, then refresh status. A missing acknowledgment
during lockdown is not proof that the command failed or succeeded.

New workspace agents include the panel automatically. For a saved workspace
created before this panel was added, reopen the SSH egress configuration editor
and **Save**, then deploy the updated workspace. This attaches the panel while
preserving other selected panels. The panel itself needs no MatrixOS source
update; the existing egress status and perimeter handlers provide its controls.

## Delivery

The agent reuses the authenticated SSH inbox format for transport controls.
Phoenix uploads signed, encrypted session heartbeats and acknowledgements.
The agent creates its ordinary `connected.flag.SESSION_ID` lease so existing
RPC producers and Log Streamer can find the relay that owns that session.
Sessions expire after 180 seconds by default; heartbeats are sent every 30
seconds while the receiver runs.

Replies are signed and encrypted into private per-session directories under
`/matrix/universes/static/UNIVERSE/persistent/AGENT_ID/comm/outgoing`.
Directories use mode `0700`; packet files use `0600`. An atomic rename exposes
each complete reply. Phoenix verifies the signature, authenticated timestamp,
recipient, session and packet ID before submitting the inner signed callback
to its normal inbound dispatcher. A signed ACK removes only the named packet
from that session. Malformed or unverified responses are not dispatched.

Replies expire after 300 seconds by default. The spool is limited to 1,024
pending replies and 64 active sessions. A full spool rejects new replies;
queued delivery is not a claim that Phoenix has handled the callback.
In-process duplicate suppression and idempotent ACKs allow retries after an
uncertain acknowledgement; exactly-once application delivery across process
crashes is not guaranteed. No command payload is executed by the egress inbox.

Persistent mode reuses the SSH connection. One-shot mode opens a new SSH
connection for each receive poll. Both use the existing pinned-host SSH helper
and existing account authority, including its established sudo SFTP behavior
when ordinary SFTP access is denied. No sudo policy is installed by this agent.

The source currently assumes the standard `/matrix` installation path, as
does the existing SSH ingress connector.
