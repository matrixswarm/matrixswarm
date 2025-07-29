import os
import sys
import json
import base64
import argparse
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA

def get_random_aes_key(length=32):
    return os.urandom(length)

def encrypt_data(data, key):
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return nonce, ciphertext, tag

def decrypt_data(nonce, tag, ciphertext, key):
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)

def generate_rsa_keypair(bits=2048):
    key = RSA.generate(bits)
    privkey_pem = key.export_key().decode()
    pubkey_pem = key.publickey().export_key().decode()
    return privkey_pem, pubkey_pem

def embed_keypair_if_marker(obj):
    # Recursively check for "privkey": "##GENERATE_KEY##"
    if isinstance(obj, dict):
        for k, v in list(obj.items()):  # Iterate over a copy!
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
    parser = argparse.ArgumentParser(description="MatrixSwarm Directive Encryption/Decryption Tool (AES-GCM + RSA embed)")
    parser.add_argument("--in", required=True, dest="infile", help="Input file (json or py)")
    parser.add_argument("--out", dest="outfile", help="Output encrypted file (for encrypt mode)")
    parser.add_argument("--key", dest="aes_key", help="Base64 AES key for decryption")
    parser.add_argument("--decrypt", action="store_true", help="Decrypt instead of encrypt")
    args = parser.parse_args()

    if args.decrypt:
        # === DECRYPTION MODE ===
        with open(args.infile, "r") as f:
            bundle = json.load(f)
        if not args.aes_key:
            print("Error: --key <base64> is required for decrypt mode.")
            sys.exit(1)
        key = base64.b64decode(args.aes_key)
        nonce = base64.b64decode(bundle["nonce"])
        tag = base64.b64decode(bundle["tag"])
        ciphertext = base64.b64decode(bundle["ciphertext"])
        try:
            decrypted = decrypt_data(nonce, tag, ciphertext, key)
            # Pretty-print
            obj = json.loads(decrypted)
            print(json.dumps(obj, indent=2))
            # Optionally, save output to file
            if args.outfile:
                with open(args.outfile, "w") as fout:
                    json.dump(obj, fout, indent=2)
        except Exception as e:
            print(f"[ERROR] Decryption failed: {e}")
            sys.exit(1)
    else:
        # === ENCRYPTION MODE ===
        with open(args.infile, "rb") as f:
            raw = f.read()
        # (Optional) If it's a .py file, only encrypt the matrix_directive structure
        try:
            if args.infile.endswith(".py"):
                from runpy import run_path
                d = run_path(args.infile)
                data = d["matrix_directive"]
            else:
                data = json.loads(raw)
        except Exception:
            data = json.loads(raw)

        pubkeys = list(embed_keypair_if_marker(data))
        data_bytes = json.dumps(data, indent=2).encode()

        key = get_random_aes_key()
        nonce, ciphertext, tag = encrypt_data(data_bytes, key)

        out = {
            "nonce": base64.b64encode(nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode()
        }
        if not args.outfile:
            print("Error: --out <output_file> is required for encrypt mode.")
            sys.exit(1)
        with open(args.outfile, "w") as f:
            json.dump(out, f, indent=2)

        print("\n[🔑] SAVE THIS AES KEY. YOU WILL NOT SEE IT AGAIN:")
        print(base64.b64encode(key).decode())
        if pubkeys:
            print("\n[🪪] PUBKEY(S) FOR ENCRYPTING MESSAGES:")
            for pub in pubkeys:
                print(pub)
        else:
            print("[ℹ️] No privkey marker found; no RSA keypair embedded.")
        print("If lost, encrypted file is unrecoverable. (This is intentional, General.)")

if __name__ == "__main__":
    main()
