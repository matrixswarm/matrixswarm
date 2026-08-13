# Security Policy

## Supported version

MatrixSwarm 1.1 is pre-release software. Security fixes are applied to the current
`main` branch. Older snapshots, branches, and the historical standalone PyPI package
may not receive security updates.

## Reporting a vulnerability

Report suspected vulnerabilities privately to **swarm@matrixswarm.com**.

Please do not open a public issue for an unpatched vulnerability. Include, when safe:

- the affected component and commit or version;
- the impact and conditions required to reproduce it;
- minimal reproduction steps;
- whether credentials, personal data, or production systems may be affected.

Do not include live credentials, private keys, tokens, personal data, customer data, or
unredacted operational logs. We will acknowledge the report, investigate it, and coordinate
a fix and disclosure based on severity and practical risk.

## Operational scope

MatrixSwarm can deploy software, execute remote commands, manage processes, and modify
runtime files. Review [OPERATIONAL-SAFETY.md](OPERATIONAL-SAFETY.md) before testing or
deployment. Use isolated non-production systems, least-privilege credentials, verified host
fingerprints, current backups, and an exercised recovery plan.
