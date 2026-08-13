# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
from .vault_store_base import VaultStore

class ConnectionStore(VaultStore):
    def __init__(self, root_vault):
        super().__init__(root_vault, "connection_manager")

    def allow_delete(self, conn_id):
        # Prevent deletion if any deployment still references this connection
        deployments = self.root.get_section("deployments") or {}
        for dep_id, meta in deployments.items():
            if conn_id in str(meta):  # simplified reference check
                return False
        return True

    def validate_key(self, conn_id, cfg):
        return (
            isinstance(cfg, dict)
            and "host" in cfg
            and "username" in cfg
            and "private_key" in cfg
        )

    def allow_delete_relations(self, conn_id):
        deployments = self.other("deployments").get_data()
        for dep_id, meta in deployments.items():
            if conn_id in str(meta):
                return False
        return True

    def validate_store(self):
        return True
