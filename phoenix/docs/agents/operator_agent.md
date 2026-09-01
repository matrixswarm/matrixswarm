# Operator Agent

`operator_agent` is an approval-gated cognitive-agent base implementation. It
keeps durable encrypted run checkpoints and reaches external tools only through
MCP Reflex.

It is intentionally inert when first added to a deployment. Before enabling
it, provision exact requester and approver UIDs, define fixed workflows, and
grant the exact deployed operator UID the matching MCP Reflex server/tool pair.

The agent records a run as `awaiting_approval`, then requires a distinct signed
approver before dispatch. A restart during dispatch marks the run
`recovery_required`; it never repeats the external call automatically.
