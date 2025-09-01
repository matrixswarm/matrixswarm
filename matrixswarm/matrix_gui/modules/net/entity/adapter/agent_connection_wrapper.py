class AgentConnectionWrapper:
    def __init__(self, agent: dict, deployment: dict):
        self.agent = agent
        self.deployment = deployment
        self.uid = agent.get('universal_id')

    def _get_connection(self) -> dict:
        return (self.agent.get('connection_snapshot')
                or self.agent.get('connection')
                or {})

    def get_universal_id(self) -> str:
        return self.uid

    @property
    def proto(self) -> str:
        return self._get_connection().get('proto')

    @property
    def host(self) -> str:
        conn = self._get_connection()
        return conn.get('host') or conn.get('ip')

    @property
    def port(self) -> int:
        return self._get_connection().get('port')

    @property
    def spki_pin(self) -> str:
        pin = self._get_connection().get('spki_pin')
        if not pin:
            pin = self.deployment.get('certs', {}) \
                                 .get(self.uid, {}) \
                                 .get('connection', {}) \
                                 .get('spki_pin')
        return pin
