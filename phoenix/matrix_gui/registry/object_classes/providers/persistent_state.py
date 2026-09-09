"""Registry presentation for durable encrypted-state profiles."""

from .base_provider import ConnectionProvider


class PersistentState(ConnectionProvider):
    def get_columns(self):
        return ["Label", "Stable State ID", "Version", "Created (UTC)", "Serial"]

    def get_default_channel_options(self):
        return []

    def get_row(self, data):
        return [
            str(data.get("label", "")),
            str(data.get("state_id", "")),
            str(data.get("key_version", 1)),
            str(data.get("created_at", "")),
            str(data.get("serial", "")),
        ]

    def get_conn_id(self, cid, data):
        return cid
