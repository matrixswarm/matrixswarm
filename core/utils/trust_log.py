import hashlib
from cryptography.hazmat.primitives import serialization
def log_trust_banner(agent_name, logger, pub, parent_pub=None, matrix_pub=None):
    def get_fp(k):
        try:
            b = k.encode() if isinstance(k, str) else k.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo
            )
            return hashlib.sha256(b).hexdigest()[:12]
        except Exception:
            return "❌ Invalid"

    lines = [
        "╔═══════════════════════════════════════╗",
        f"║ 🔐 TRUST LINEAGE - {agent_name:<21}║",
        f"║ 🧬 SELF:   {get_fp(pub):<12}              ║",

        "╚═══════════════════════════════════════╝"
    ]
    for line in lines:
        logger.log(line)