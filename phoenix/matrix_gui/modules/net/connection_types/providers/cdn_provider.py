# Authored by Daniel F MacDonald and ChatGPT-5 (“The Generals”)
from .base_provider import ConnectionProviderInterface

class CDN(ConnectionProviderInterface):
    """
    Provides CDN connection data for the Connection Manager dialog.
    Mirrors the SSH provider pattern but exposes CDN-specific fields.
    """

    def get_columns(self):
        return ["Label", "Host", "User", "Auth", "Remote Path", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["cdn.upload", "cdn.verify", "cdn.alerts"]

    def get_row(self, data, used_in):
        return [
            data.get("label", ""),
            data.get("host", ""),
            data.get("username", ""),
            data.get("auth_type", ""),
            data.get("remote_path", ""),
            data.get("default_channel", ""),
            data.get("serial", ""),
        ]

    def get_conn_id(self, cid, data):
        return cid
