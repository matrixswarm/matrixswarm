#!/usr/bin/env python3
# Authored by Daniel F MacDonald and ChatGPT aka The Generals
# Docstrings by Gemini

"""
MatrixSwarm Directive Encryption & Packaging Tool.

This script provides a command-line interface to secure MatrixSwarm directives.
It packages directives for deployment by encrypting them and can embed
necessary components like agent source code and cryptographic keys.

Core Features:
-   **Encryption/Decryption**: Secures the entire directive using AES-256-GCM,
    ensuring confidentiality and integrity.
-   **Source Code Embedding (`--clown-car`)**: Automatically finds agent source
    code and embeds it as a base64 string within the directive, creating a
    self-contained, portable package.
-   **Integrity Hashing (`--hash-bang`)**: Calculates a SHA256 hash of each
    agent's source code and embeds it in the directive as `hash_bang`. The
    CoreSpawner uses this hash to verify that the code has not been altered
    before execution, preventing tampering.
-   **Dynamic Key Generation**: Can generate and embed new RSA key pairs wherever
    a "##GENERATE_KEY##" marker is found.

Encryption Mode Usage:
    # Encrypt, embed source, and add integrity hashes
    python encrypt_directive.py --in my_directive.py --out encrypted.json --clown-car --hash-bang

Decryption Mode Usage:
    python encrypt_directive.py --in encrypted.json --decrypt --key <YOUR_AES_KEY>
"""
import os
import sys
import json
import base64
import argparse
import hashlib
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from pathlib import Path


def get_random_aes_key(length=32):
    """
    Generates a cryptographically secure random key.

    Args:
        length (int, optional): The desired length of the key in bytes.
                                Defaults to 32 (for AES-256).

    Returns:
        bytes: A random byte string of the specified length.
    """
    return os.urandom(length)


def encrypt_data(data, key):
    """
    Encrypts data using AES in GCM mode.

    GCM (Galois/Counter Mode) is an authenticated encryption mode that provides
    both confidentiality and data integrity.

    Args:
        data (bytes): The data to encrypt.
        key (bytes): The AES encryption key (16, 24, or 32 bytes).

    Returns:
        tuple: A tuple containing the nonce (bytes), ciphertext (bytes),
               and tag (bytes).
    """
    nonce = os.urandom(12)  # GCM nonce, 12 bytes is a common choice
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return nonce, ciphertext, tag


def decrypt_data(nonce, tag, ciphertext, key):
    """
    Decrypts data using AES in GCM mode and verifies its integrity.

    Args:
        nonce (bytes): The nonce used during encryption.
        tag (bytes): The authentication tag generated during encryption.
        ciphertext (bytes): The encrypted data.
        key (bytes): The AES encryption key.

    Returns:
        bytes: The decrypted plaintext data.

    Raises:
        ValueError: If the key is incorrect or the message has been tampered with.
    """
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)


def generate_rsa_keypair(bits=2048):
    """
    Generates a new RSA public/private key pair.

    Args:
        bits (int, optional): The key length in bits. Defaults to 2048.

    Returns:
        tuple: A tuple containing the private key (str) and public key (str)
               in PEM format.
    """
    key = RSA.generate(bits)
    privkey_pem = key.export_key().decode()
    pubkey_pem = key.publickey().export_key().decode()
    return privkey_pem, pubkey_pem


def embed_agent_sources(directive, base_path=None):
    """
    Recursively finds agent definitions, reads their source code, and embeds
    it as a base64 encoded string in a 'src_embed' field.

    This is the "clown-car" feature, allowing a directive to carry all
    necessary agent code within it for portable deployment.

    Args:
        directive (dict or list): The directive structure to process.
        base_path (str, optional): The root path of the MatrixSwarm installation,
                                   used for resolving agent paths. Defaults to None.
    """
    if isinstance(directive, dict):
        agent_name = directive.get("name")
        src_path = directive.get("src")
        # Auto-infer src path if not present and agent name is standard
        if not src_path and agent_name and base_path:
            test_path = os.path.join(base_path, "agent", agent_name, f"{agent_name}.py")
            if os.path.exists(test_path):
                src_path = test_path
                directive["src"] = test_path  # Update directive with inferred path

        if src_path and os.path.exists(src_path):
            with open(src_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode()
            directive["src_embed"] = encoded

        # Recurse into child values
        for v in directive.values():
            embed_agent_sources(v, base_path=base_path)
    elif isinstance(directive, list):
        for item in directive:
            embed_agent_sources(item, base_path=base_path)

def set_hash_bang(directive, base_path=None):
    """
    Recursively finds agent definitions and sets a 'hash_bang' field containing
    the SHA256 hash of the agent's source code.

    This provides a mechanism for the spawner to verify the integrity of the
    agent code before execution, preventing tampering. It hashes the embedded
    source code (`src_embed`) if it exists, otherwise it hashes the source file
    from the filesystem.

    Args:
        directive (dict or list): The directive structure to process.
        base_path (str, optional): The root path of the MatrixSwarm installation,
                                   used for resolving agent paths. Defaults to None.
    """
    if isinstance(directive, dict):
        agent_name = directive.get("name")
        src_path = directive.get("src")
        if not src_path and agent_name and base_path:
            test_path = os.path.join(base_path, "agent", agent_name, f"{agent_name}.py")
            if os.path.exists(test_path):
                src_path = test_path
        if "src_embed" in directive:
            # Hash the embedded base64 code
            src_bytes = base64.b64decode(directive["src_embed"])
            directive["hash_bang"] = hashlib.sha256(src_bytes).hexdigest()
        elif src_path and os.path.exists(src_path):
            with open(src_path, "rb") as f:
                directive["hash_bang"] = hashlib.sha256(f.read()).hexdigest()
        # Recurse
        for v in directive.values():
            set_hash_bang(v, base_path=base_path)
    elif isinstance(directive, list):
        for item in directive:
            set_hash_bang(item, base_path=base_path)


def ensure_boot_directives_path(filename):
    """
    Ensures that a directive filename points to the correct location within
    the .matrixswarm/boot_directives/ directory if a relative path is given.

    Args:
        filename (str): The input or output filename from the command line.

    Returns:
        str: The resolved, absolute path to the directive file.
    """
    # If filename is absolute or contains a path, use as is
    if os.path.isabs(filename) or os.path.dirname(filename):
        return filename
    # Otherwise, resolve to .matrixswarm/boot_directives/ + filename
    ms_path = find_matrixswarm_path()
    return str(ms_path / "boot_directives" / filename)

def find_matrixswarm_path(cli_path=None):
    """
    Finds the root directory of the MatrixSwarm installation.

    It searches in the following order:
    1. A path provided via the command line.
    2. A '.swarm' file in the current or parent directories.
    3. The 'MATRIXSWARM_PATH' environment variable.
    4. A '.matrixswarm' subdirectory in the current directory.

    Args:
        cli_path (str, optional): A path provided from the command line.

    Returns:
        pathlib.Path: The resolved absolute path to the MatrixSwarm root.
    """
    if cli_path:
        return Path(cli_path).expanduser().resolve()
    here = Path.cwd()
    for parent in [here] + list(here.parents):
        swarm_pointer = parent / ".swarm"
        if swarm_pointer.exists():
            with open(swarm_pointer) as f:
                return Path(f.read().strip()).expanduser().resolve()
    env_path = os.environ.get("MATRIXSWARM_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return here / ".matrixswarm"


def embed_keypair_if_marker(obj):
    """
    Recursively searches a directive for a "##GENERATE_KEY##" marker and
    replaces it with a newly generated RSA public/private key pair.

    Args:
        obj (dict or list): The directive structure to process.

    Yields:
        str: The public key of each generated key pair.
    """
    if isinstance(obj, dict):
        for k, v in list(obj.items()):  # Iterate over a copy for safe modification
            if k == "privkey" and v == "##GENERATE_KEY##":
                priv, pub = generate_rsa_keypair()
                obj[k] = priv
                obj["pubkey"] = pub
                yield pub
            else:
                yield from embed_keypair_if_marker(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from embed_keypair_if_marker(item)


def main():
    """
    Main function to parse command-line arguments and run the tool in either
    encryption or decryption mode.
    """
    parser = argparse.ArgumentParser(description="MatrixSwarm Directive Encryption/Decryption Tool (AES-GCM + RSA embed)")
    parser.add_argument("--in", required=True, dest="infile", help="Input file (json or py)")
    parser.add_argument("--out", dest="outfile", help="Output file (required for encrypt mode)")
    parser.add_argument("--key", dest="aes_key", help="Base64 encoded AES key for decryption")
    parser.add_argument("--decrypt", action="store_true", help="Run in decryption mode instead of encryption")
    parser.add_argument("--clown-car", action="store_true", help="Embed all agent source code as base64 in 'src_embed'")
    parser.add_argument("--hash-bang", action="store_true", help="SHA256 hash each agent source and set 'hash_bang' in all nodes")

    args = parser.parse_args()

    args.infile = ensure_boot_directives_path(args.infile)
    if args.outfile:
        args.outfile = ensure_boot_directives_path(args.outfile)

    if args.decrypt:
        # --- DECRYPTION MODE ---
        with open(args.infile, "r") as f:
            bundle = json.load(f)
        if not args.aes_key:
            print("Error: --key <base64> is required for decrypt mode.", file=sys.stderr)
            sys.exit(1)

        try:
            key = base64.b64decode(args.aes_key)
            nonce = base64.b64decode(bundle["nonce"])
            tag = base64.b64decode(bundle["tag"])
            ciphertext = base64.b64decode(bundle["ciphertext"])
            decrypted = decrypt_data(nonce, tag, ciphertext, key)
            obj = json.loads(decrypted)

            # Pretty-print to stdout
            print(json.dumps(obj, indent=2))

            # Optionally, save output to a file
            if args.outfile:
                with open(args.outfile, "w") as fout:
                    json.dump(obj, fout, indent=2)
                print(f"\n[✅] Decrypted directive saved to {args.outfile}", file=sys.stderr)

        except (ValueError, KeyError) as e:
            print(f"[❌ ERROR] Decryption failed. The key may be wrong or the file corrupted: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # --- ENCRYPTION MODE ---
        if not args.outfile:
            print("Error: --out <output_file> is required for encrypt mode.", file=sys.stderr)
            sys.exit(1)

        try:
            with open(args.infile, "rb") as f:
                raw_content = f.read()

            # If it's a .py file, try to extract the 'matrix_directive' dictionary
            if args.infile.endswith(".py"):
                from runpy import run_path
                d = run_path(args.infile)
                data = d["matrix_directive"]
            else:
                data = json.loads(raw_content)
        except (IOError, KeyError, json.JSONDecodeError) as e:
            print(f"[❌ ERROR] Failed to read or parse input file '{args.infile}': {e}", file=sys.stderr)
            sys.exit(1)

        # Embed agent source code if requested
        matrixswarm_base = find_matrixswarm_path()
        if args.clown_car:
            print("[🤡] Embedding agent sources (clown-car mode)...", file=sys.stderr)
            embed_agent_sources(data, base_path=str(matrixswarm_base))

        if args.hash_bang:
            print("[🔒] Calculating SHA256 'hash_bang' for all agents...", file=sys.stderr)
            set_hash_bang(data, base_path=str(matrixswarm_base))

        # Generate and embed RSA key pairs if markers are found
        pubkeys = list(embed_keypair_if_marker(data))

        # Encrypt the final directive structure
        data_bytes = json.dumps(data, indent=2).encode()
        key = get_random_aes_key()
        nonce, ciphertext, tag = encrypt_data(data_bytes, key)

        # Prepare the output bundle
        out_bundle = {
            "nonce": base64.b64encode(nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode()
        }

        with open(args.outfile, "w") as f:
            json.dump(out_bundle, f, indent=2)

        print(f"\n[✅] Encrypted directive saved to {args.outfile}", file=sys.stderr)
        print("\n" + "=" * 50, file=sys.stderr)
        print("[🔑] SAVE THIS AES KEY. YOU WILL NOT SEE IT AGAIN:", file=sys.stderr)
        print(base64.b64encode(key).decode())
        print("=" * 50 + "\n", file=sys.stderr)

        if pubkeys:
            print("[🪪] Generated Public Key(s) for external use:", file=sys.stderr)
            for pub in pubkeys:
                print(pub, file=sys.stderr)
        else:
            print("[ℹ️] No '##GENERATE_KEY##' marker found; no RSA keypair embedded.", file=sys.stderr)

        print("\nIf the AES key is lost, the encrypted file is unrecoverable.", file=sys.stderr)


if __name__ == "__main__":
    main()