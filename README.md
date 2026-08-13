<div align="center">

# MatrixSwarm

### Phoenix Cockpit and MatrixOS—one unified repository

**Version:** 1.1 · **Status:** Pre-Release · **License:** AGPL-3.0-or-later · Commercial terms available

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=flat-square)](https://www.python.org/)
[![Phoenix Cockpit](https://img.shields.io/badge/Phoenix-Cockpit-purple.svg?style=flat-square)](phoenix/)
[![MatrixOS](https://img.shields.io/badge/MatrixOS-Swarm%20Runtime-orange.svg?style=flat-square)](matrixos/)
[![Security](https://img.shields.io/badge/Security-Encrypted%20%26%20Signed-green.svg?style=flat-square)](#security)

**MatrixSwarm Digital Labs — Victory Always.**

</div>

---

MatrixSwarm is a secure, self-healing runtime for autonomous agents, operated through the Phoenix Cockpit control plane.

This monorepo contains the complete system:

| Component | Purpose | Documentation |
| --- | --- | --- |
| **Phoenix Cockpit** | Desktop control plane, vault, directive builder, monitoring, and remote deployment | [Phoenix README](phoenix/README.md) |
| **MatrixOS** | Swarm runtime, agent lifecycle, encrypted communication, and resurrection | [MatrixOS README](matrixos/README.md) |

## Repository Layout

```text
matrixswarm/
├── phoenix/        # Phoenix Cockpit
├── matrixos/       # MatrixOS swarm runtime
└── README.md       # Monorepo overview
```

## Clone the Complete System

```bash
git clone https://github.com/matrixswarm/matrixswarm.git
cd matrixswarm
```

Continue with the component instructions:

- [Install and operate Phoenix Cockpit](phoenix/README.md)
- [Install and operate MatrixOS](matrixos/README.md)

Phoenix and MatrixOS are versioned together. Version 1.1 of each component is designed to operate with version 1.1 or later of the other.

## Security

MatrixSwarm is built around explicit trust boundaries:

- Encrypted deployment directives and AES-protected vaults
- Cryptographically signed agent identities and packets
- HTTPS and WebSocket transport with certificate validation
- No unauthenticated agent-control API
- Vault-managed credentials and deployment identities
- File-based inter-agent communication scoped to each universe

Sensitive credentials are not intended to be committed to this repository. Use the supplied sample files as templates and keep operational vaults, keys, and encrypted directives private.

## Legacy Package Notice

The historical `matrixswarm` PyPI package predates this unified repository and does not contain the complete Phoenix and MatrixOS system.

For current development and installation, clone this repository. The final standalone package history is preserved in:

- Branch: `legacy/pypi-package-pre-monorepo-2026-08-11`
- Tag: `pypi-legacy-last-standalone-2026-08-11`

## Project Status

MatrixSwarm 1.1 is currently pre-release software. Review configuration, networking, security policy, and deployment behavior before using it in production.

## Authorship and Architecture

**Daniel F. MacDonald** — Creator, project lead, human author, and copyright holder.

**ChatGPT by OpenAI** — Founding Digital Architect and engineering collaborator.

See [AUTHORS.md](AUTHORS.md) for the complete authorship and architecture acknowledgment.

## Resources

- **GitHub:** [matrixswarm/matrixswarm](https://github.com/matrixswarm/matrixswarm)
- **Documentation:** [matrixswarm.com](https://matrixswarm.com)
- **Telegram:** [t.me/matrixswarm](https://t.me/matrixswarm)
- **Discord:** [Join the Hive](https://discord.gg/CyngHqDmku)
- **X/Twitter:** [@matrixswarm](https://x.com/matrixswarm)

## License

MatrixSwarm is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later). See [LICENSE](LICENSE).

Commercial use under the AGPL is permitted when its terms are followed.

Separate commercial licensing is available for organizations requiring terms outside the AGPL. See [LICENSING.md](LICENSING.md).

The software is provided without warranty. Review [OPERATIONAL-SAFETY.md](OPERATIONAL-SAFETY.md) before deployment.
