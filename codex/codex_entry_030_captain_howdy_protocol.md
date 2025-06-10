# 🤡 codex_entry_030: Captain Howdy Protocol

## Summary

The Captain Howdys are not a conventional unit. They do not flank.  
They do not negotiate.  
They **infiltrate**.

This protocol describes the deployment of role-based RPC reflex agents that route packets not to a single destination, but through a decentralized swarm of surgical responders.

## Directive

Any agent with `"role": "hive.rpc.route"` becomes a Captain Howdy node.  
All telemetry dispatches — price changes, conversions, threshold hits — are sent via:

```json
{
  "handler": "cmd_forward_command",
  "content": {
    "target_universal_id": "X",
    "folder": "incoming",
    "command": {
      "handler": "crypto_agent_update",
      "filetype": "msg",
      "content": {...}
    }
  }
}
