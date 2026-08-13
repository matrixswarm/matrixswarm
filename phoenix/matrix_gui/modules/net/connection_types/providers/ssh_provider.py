from .base_provider import ConnectionProviderInterface

class SSH(ConnectionProviderInterface):

    def get_columns(self):
        return ["Label", "Host", "Port", "User", "Auth", "Fingerprint", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        # Agents usually use SSH for outgoing ops
        return ["ssh.command", "ssh.copy", "alerts"]

    def get_row(self, data, used_in):
        return [
            data.get("label", ""),
            data.get("host", ""),
            str(data.get("port", "")),
            data.get("username", ""),
            data.get("auth_type", ""),                   # password / private_key / agent
            data.get("trusted_host_fingerprint", ""),    # SHA256:xxxx
            data.get("default_channel", ""),
            data.get("serial", ""),
        ]

    def get_conn_id(self, cid, data):
        return cid
