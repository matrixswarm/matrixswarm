🛡️ Swarm Deployment & Directive Workflow
🎯 Primary Goals

Vault-driven deployment: Eliminate loose cert handling, manual inputs, and repeated cert reuse.

Security isolation: Ensure every swarm is cryptographically unique, preventing cross-contamination.

Enterprise UX: Simple GUI for operators with clear steps for deploying secure Matrix swarms.

🗃️ Key Definitions
🔑 Swarm Key (swarm_key):

AES symmetric encryption key.

Clearly generated per deployment.

Encrypts the final directive.

Used for secure log decryption later.

🧾 Directive (encrypted):

Minted from a template directive combined with a deployment record.

Includes only security-tag-defined cert fields per agent.

Retained inside the encrypted Phoenix vault and streamed to MatrixD over a pinned SSH channel.

📚 Deployment Record (vault stored):

Flat structure (agents[]) with all cert pairs (priv/pub keys, certs, CA, serial).

Stores swarm_key, encrypted_hash, encrypted_bundle, universe, interfaces (IP, ports, cert fingerprints).

Internal GUI reference, never uploaded directly.

⚙️ Security Tag Mapping

Agents receive cert fields clearly based on this mapping:

Security Tag	Assigned Cert Fields
queen	privkey, remote_pubkey, serial
perimeter_https	privkey, remote_pubkey, cert, key, ca, serial, spki_pin
perimeter_websocket	privkey, remote_pubkey, cert, key, ca, serial, spki_pin
def get_security_tags():
    return {
        "queen": {
            "signing": ["privkey", "remote_pubkey"],
            "serial": ["serial"]
        },
        "perimeter_https": {
            "signing": ["privkey", "remote_pubkey"],
            "connection": ["cert", "key", "ca", "serial", "spki_pin"],
            "serial": ["serial"]
        },
        "perimeter_websocket": {
            "signing": ["privkey", "remote_pubkey"],
            "connection": ["cert", "key", "ca", "serial", "spki_pin"],
            "serial": ["serial"]
        }
    }

🚀 Clear Numbered Deployment Steps

Follow these clearly numbered steps when deploying a new swarm via your GUI:

1️⃣ Select Template Directive

Choose saved directive clearly from the vault.

2️⃣ Create Deployment Record

Generate unique deployment_id (deployment_<uuid>).

Clearly prompt for user-friendly deployment label.

3️⃣ Deep Copy Directive Template

Clearly copy directive JSON structure as sealed.

4️⃣ Assign Connections

Use ConnectionAssignmentDialog.

Clearly match agents with connection details from vault's connection manager.

5️⃣ Inject Certs & Flatten

Run inject_all_tags_into_deployment(sealed) clearly to insert certs.

Flatten sealed clearly (agents list without children/config).

6️⃣ Save Flattened Deployment

Store in vault:

agents[] with all cert details.

label, source_directive, timestamp (deployed_at).

7️⃣ Mint Runtime Directive

Copy original template again (runtime_directive).

Clearly match and insert cert fields per agent (by universal_id) from flattened deployment.

Add any missing fields clearly and explicitly.

8️⃣ Apply Optional Fields (Clown Car / Hashbang)

Optional clearly embedded agent sources.

Optional _hashbang for directive integrity verification.

9️⃣ Operator Preview

Display runtime directive clearly to operator.

Clearly prompt for confirmation.

Operator rejects: clearly abort deployment process.

🔟 Generate AES Swarm Key & Encrypt Directive

Generate a fresh AES swarm_key.

Encrypt runtime directive clearly with generate_swarm_encrypted_directive(...).

1️⃣1️⃣ Seal for Railgun

Keep the encrypted directive bundle and swarm key inside the encrypted Phoenix vault. Do not create loose directive or key files.

1️⃣2️⃣ Update Deployment Record

Compute SHA256 hash of the canonical encrypted bundle (encrypted_hash).

Clearly update vault deployment record:

Store swarm_key (base64-encoded).

encrypted_bundle, universe, encrypted_hash.

Clearly-defined interfaces (IP/port, cert fingerprints).

1️⃣3️⃣ Update Vault & Refresh GUI

Emit vault update event: EventBus.emit("vault.update", ...).

Clearly refresh GUI deployment listings.

1️⃣4️⃣ Railgun Stream + Boot

Stream one bounded sealed envelope over the pinned SSH channel to `matrixd boot --directive-stdin`. The envelope is accepted only on stdin and is decrypted in memory; neither its directive nor swarm key is placed in argv, environment variables, or remote boot files.

🎯 Final Workflow Diagram (clearly illustrated)
flowchart LR
  TD[Template Directive from Vault]
  Deployment{Deployment Record - Flat Agents & Certs}
  Runtime[Minted Runtime Directive]
  ENC[Encrypted Directive Bundle in Phoenix Vault]
  SV[Vault Save - Swarm Key, Hash, Interfaces]

  TD --> Deployment --> Runtime --> ENC --> SV
  ENC --> RG[Railgun SSH Stdin] --> MD[MatrixD In-Memory Decrypt]

📌 Important Outcomes (clearly stated):

Each swarm clearly isolated cryptographically.

Vault clearly acts as the central truth.

GUI clearly guides operators step-by-step.

Encryption & certificate management clearly handled internally.

Operators clearly verify the directive before encryption.

Secure, auditable, enterprise-ready workflow clearly in place.
