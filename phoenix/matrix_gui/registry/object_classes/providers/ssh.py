from .base_provider import ConnectionProvider

class SSH(ConnectionProvider):

    def get_columns(self):
        return ["Label", "Host", "Port", "User", "Auth", "Fingerprint", "Serial"]

    def get_default_channel_options(self):
        # Runtime routing belongs to the consuming agent, not this credential.
        return []

    def get_row(self, data):
        return [
            data.get("label", ""),
            data.get("host", ""),
            str(data.get("port", "")),
            data.get("username", ""),
            data.get("auth_type", ""),                   # password / private_key / agent
            data.get("trusted_host_fingerprint", ""),    # SHA256:xxxx
            data.get("serial", ""),
        ]

    def get_conn_id(self, cid, data):
        return cid
