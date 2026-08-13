# Commander Edition – POP3 Provider
from .base_provider import ConnectionProvider

class POP3(ConnectionProvider):

    def get_columns(self):
        return ["Label", "User", "Server", "Port", "Encryption", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["alerts"]

    def get_row(self, data):
        return [
            data.get("label", ""),
            data.get("incoming_username", ""),
            data.get("incoming_server", ""),
            str(data.get("incoming_port", "")),
            data.get("incoming_encryption", ""),
            data.get("default_channel", ""),
            data.get("serial", ""),
        ]

    def get_conn_id(self, cid, data):
        return cid
