# MatrixSwarm Operational Safety Notice

MatrixSwarm, Phoenix Cockpit, and MatrixOS are powerful automation and remote-administration tools. They can execute commands, deploy or replace software, create and terminate processes, modify files, rotate runtime state, communicate over networks, and interact with third-party systems.

This notice summarizes important operational risks and recommended safeguards. It is informational, is not professional advice, and does not modify the GNU Affero General Public License or create any warranty, support obligation, or service-level commitment.

## No Warranty and Limitation of Liability

The software is provided under the GNU AGPL without warranty, as described in Sections 15 and 16 of that license. Those sections also address limitation of liability to the extent permitted by applicable law.

No software can guarantee prevention of data loss, service interruption, security incidents, unexpected costs, configuration damage, or incompatibility with a particular environment. Commercial warranties or support obligations exist only when stated in a separate written agreement signed by the applicable parties.

## Operator Responsibilities

Before using MatrixSwarm, the operator is responsible for:

- Reviewing commands, deployment scripts, directives, agents, and configuration before execution.
- Confirming the identity of every target host, universe, deployment, account, mailbox, directory, and external service.
- Maintaining tested, offline, and recoverable backups of affected systems and data.
- Testing changes in an isolated, non-production environment before production use.
- Applying least-privilege access and avoiding root or administrator access unless required.
- Protecting vaults, private keys, tokens, certificates, passwords, recovery material, and encrypted directives.
- Confirming that destructive operations have the intended scope and that rollback procedures work.
- Monitoring resource consumption, network activity, logs, queues, storage, email retention, and third-party usage charges.
- Following applicable laws, regulations, contracts, provider terms, privacy requirements, retention duties, and security policies.
- Installing compatible dependencies and validating operating-system, Python, network, certificate, and service requirements.

## High-Impact Operations

Treat the following as potentially destructive or service-affecting:

- Railgun installation, reinstall, overwrite, synchronization, and remote shell execution.
- Universe kill, restart, reboot, clean, rug-pull, hotswap, source replacement, and agent deletion.
- Recursive file operations, mirrored synchronization, runtime cleanup, mailbox deletion, and retention cleanup.
- Credential rotation, certificate replacement, trust-store changes, firewall changes, and transport switching.
- Automated responses generated from untrusted, malformed, stale, replayed, or incorrectly addressed input.

Use explicit target confirmation, concurrency controls, timeouts, audit logging, backups, and tested recovery procedures for these operations.

## Production Deployment Checklist

Before production use:

1. Create and verify a complete backup.
2. Test restoration on a separate system.
3. Validate the selected host and deployment identity.
4. Review every enabled agent and its permissions.
5. Confirm network exposure, firewall policy, TLS configuration, certificate pins, and authentication.
6. Verify disk space, memory, CPU, time synchronization, Python dependencies, and service accounts.
7. Exercise stop, rollback, recovery, and credential-revocation procedures.
8. Enable monitoring and preserve sufficient logs for diagnosis without recording secrets.
9. Run a limited pilot before expanding scope.

## Security Reports

Report suspected vulnerabilities privately to:

**swarm@matrixswarm.com**

Remove credentials, private keys, personal data, and other sensitive material from reports and logs. Include the affected version, component, impact, and reproducible steps when safe to do so.

## Acceptance of Operational Risk

Running the software means operating automation within an environment chosen and controlled by the operator. The operator should proceed only after evaluating the risks, confirming authorization, and deciding that the safeguards are appropriate for that environment.
