import os

DEFAULT_VAULT_DIR = os.path.abspath(
    os.getenv(
        "MATRIX_VAULT_DIR",
        os.path.join(os.path.dirname(__file__), "../../../config/vaults")
    )
)

def ensure_vault_dir():
    os.makedirs(DEFAULT_VAULT_DIR, exist_ok=True)
    return DEFAULT_VAULT_DIR