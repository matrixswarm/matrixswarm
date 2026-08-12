# Commander Edition – SMTP Provider
from .base_provider import ConnectionProvider

class SMTP(ConnectionProvider):

    def get_columns(self):
        return ["Label", "User", "Server", "Port", "Encryption", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["alerts"]

    def get_row(self, data):
        return [
            data.get("label", ""),
            data.get("smtp_username", ""),
            data.get("smtp_server", ""),
            str(data.get("smtp_port", "")),
            data.get("smtp_encryption", ""),
            data.get("default_channel", ""),
            data.get("serial", ""),
        ]

    def get_conn_id(self, cid, data):
        return cid
