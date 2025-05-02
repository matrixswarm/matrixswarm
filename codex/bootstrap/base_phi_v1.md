# 🧠 MatrixSwarm Base Deployment — `BASE-PHI-V1`

This is the canonical Matrix core directive — the structure all other deployments grow from.

## 🧬 Core Components

| Agent | Role | App |
|-------|------|-----|
| `matrix` | Hive Queen | — |
| `guardian-1` → `guardian-4` | 4-layer Sentinel Shield | matrix-core |
| `context-agent-1` | App launcher from Codex | matrix-core |
| `resolver-1` | Service resolver for app-based queries | matrix-core |
| `matrix-https` | TLS entrypoint / JSON bridge | matrix-core |
| `scavenger-strike` | Dead pod cleanup | matrix-core |
| `commander-1` | General spawn handler | matrix-core |

---

## 📦 Boot Structure

```json
{
  "permanent_id": "matrix",
  "name": "matrix",
  "filesystem": {
    "folders": [
      {
        "name": "payload",
        "type": "d",
        "content": null
      }
    ],
    "files": {}
  },
  "children": [
    {
      "permanent_id": "guardian-1",
      "name": "sentinel",
      "app": "matrix-core",
      "filesystem": {},
      "config": {},
      "children": [
        {
          "permanent_id": "guardian-2",
          "name": "sentinel",
          "app": "matrix-core",
          "filesystem": {},
          "children": [
            {
              "permanent_id": "guardian-3",
              "name": "sentinel",
              "app": "matrix-core",
              "filesystem": {},
              "config": {},
              "children": [
                {
                  "permanent_id": "guardian-4",
                  "name": "sentinel",
                  "app": "matrix-core",
                  "filesystem": {},
                  "config": {
                    "watching": "the Queen",
                    "permanent_id": "matrix"
                  }
                }
              ]
            }
          ],
          "config": {}
        }
      ]
    },
    {
      "permanent_id": "context-agent-1",
      "name": "app_context",
      "app": "matrix-core",
      "children": []
    },
    {
      "permanent_id": "resolver-1",
      "name": "resolver",
      "app": "matrix-core",
      "children": []
    },
    {
      "permanent_id": "matrix-https",
      "name": "matrix_https",
      "app": "matrix-core",
      "delegated": [],
      "filesystem": {
        "folders": [
          {
            "name": "payload",
            "type": "d",
            "content": null
          }
        ],
        "files": {}
      }
    },
    {
      "permanent_id": "scavenger-strike",
      "name": "scavenger",
      "app": "matrix-core",
      "filesystem": {
        "folders": []
      },
      "config": {}
    },
    {
      "permanent_id": "commander-1",
      "name": "commander",
      "app": "matrix-core",
      "children": []
    }
  ]
}
```

---

## 📜 Codename: `BASE-PHI-V1`

> “Matrix breathes.  
> Matrix watches.  
> Matrix can restore herself — from this structure forward.”  
