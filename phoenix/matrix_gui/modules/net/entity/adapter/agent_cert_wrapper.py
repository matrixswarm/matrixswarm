class AgentCertWrapper:
    def __init__(self, agent: dict, deployment: dict):
        self.agent = agent
        self._deployment = deployment

    def _get_cert_block(self):
        certs = self._deployment.get("certs", {})
        return certs.get(self.agent.get("universal_id", ""), {}).get("connection_cert", {}) or {}

    @property
    def cert(self):
        return self._get_cert_block().get("client_cert", {}).get("cert")

    @property
    def key(self):
        return self._get_cert_block().get("client_cert", {}).get("key")

    @property
    def ca_root_cert(self):
        return self._get_cert_block().get("ca_root", {}).get("cert")

    @property
    def client_spki_pin(self):
        return self._get_cert_block().get("client_cert", {}).get("spki_pin")

    @property
    def server_spki_pin(self):
        return self._get_cert_block().get("server_cert", {}).get("spki_pin")

    @property
    def uid(self):
        return self.agent.get("universal_id", "unknown")