# 🧠 MatrixSwarm Team Deployment Logic

This document outlines the launch flow for agents and teams within the MatrixSwarm system.

> MatrixSwarm operates through JSON directives and tree-based delegation. 
> Agents spawn under target nodes and expand the tree structure with delegated agents.

---

## 🌀 STEP 1: SELECT TEAM
Choose a mission file from `/deploy/teams/`

Each file should follow this structure:
```json
{
  "universal_id": "recon-unit",
  "agent_name": "ReconAgent",
  "delegated": ["scout-1", "logger-2"]
}
```
- `universal_id`: the primary agent’s permanent ID
- `agent_name`: name of the source class
- `delegated`: list of children to spawn

---

## 🧩 STEP 2: SELECT TARGET (Parent)
Pick a node from the current tree (e.g., `commander-1`)
This becomes the **launch point** in the agent hierarchy.

---

## 🚀 STEP 3: LAUNCH TEAM

Once confirmed, MatrixSwarm recursively injects the full structure:

```
launch_team()
├── spawn_agent(recon-unit)
│   ├── spawn_agent(scout-1)
│   └── spawn_agent(logger-2)
```

- Each agent receives a `/pod/` runtime and `/comm/` structure
- Delegated agents are spawned as children
- Tree updates live

---

## 🎯 ALTERNATE PATH: DIRECT AGENT LAUNCH

Use for individual agents with no delegation:
```
launch_agent()
└── spawn_agent(logger-3)
```
- Injects directly under the selected parent
- Useful for testing or one-shot deployments

---

## 🧠 KEY TAKEAWAYS

| Action           | Effect                                  |
|------------------|------------------------------------------|
| Team Launch       | Tree expands with full delegation chain |
| Single Agent      | One node is injected                    |
| Delegated Agents  | Automatically attached as children      |
| Tree              | Auto-updates with every agent           |
| Codex             | Can register agent metadata             |

---

## 🔧 Optional Enhancements

- `dry_run`: simulate without spawn
- `preview_tree`: show branch before injection
- `register_to_codex`: log new agents with banner

---

## 💬 Final Thought

MatrixSwarm launches agents like neurons firing — fast, recursive, intentional.
Each mission expands the Hive.
Each agent leaves a log.

🧠⚔️