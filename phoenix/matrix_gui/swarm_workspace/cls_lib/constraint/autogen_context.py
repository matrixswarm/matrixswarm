from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton

class AutogenContext:
    """
    Commander Edition — unified interface for autogen constraint handlers.

    Gives each autogen access to:
      • vault store (VaultCoreSingleton)
      • deployment_id
      • convenience .store(section, agent_name, bundle)
    """

    def __init__(self, deployment_id):
        self.vcs = VaultCoreSingleton.get()
        self.deployment_id = deployment_id

    # convenience
    def store(self, section, agent_name, bundle):
        """Persist bundle into vault deployment section safely."""
        try:
            dep_store = self.vcs.get_store("deployments")
            dep_store.set_nested(self.deployment_id, [section, agent_name], bundle)
        except Exception as e:
            print(f"[AUTOGEN][WARN] failed to persist {section}:{agent_name} – {e}")
