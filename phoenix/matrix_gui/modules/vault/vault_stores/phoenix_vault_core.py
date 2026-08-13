# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
from .deployment_store import DeploymentStore
from .directive_store import DirectiveStore
from .connection_store import ConnectionStore
from .workplace_store import WorkspaceStore
from .registry_store import RegistryStore
class PhoenixVaultCore:
    """
    Internal domain store manager.
    Binds stores to the VaultCoreSingleton.
    """

    def __init__(self, root_vault):
        self.root = root_vault
        self._stores ={}
        try:
            self._stores['deployments'] = DeploymentStore(self.root)
        except Exception as e:
            print(f"{str(e)}")
        try:
            self._stores['directives'] = DirectiveStore(self.root)
        except Exception as e:
            print(f"{str(e)}")
        try:
            self._stores['connection_manager'] = ConnectionStore(self.root)
        except Exception as e:
            print(f"{str(e)}")

        try:
            self._stores['workspaces'] = WorkspaceStore(self.root)
        except Exception as e:
            print(f"{str(e)}")
        try:
            self._stores['registry'] = RegistryStore(self.root)
        except Exception as e:
            print(f"{str(e)}")


    def get_store(self, name: str):
        if name not in self._stores:
            raise KeyError(f"Store '{name}' not registered")
        return self._stores[name]
