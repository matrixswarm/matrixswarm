from .base_provider import ConnectionProviderInterface


class MySQL(ConnectionProviderInterface):

    def get_columns(self):
        return ["Label", "Host", "Port", "User", "DB", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["trend_scout.mysql", "alerts", "ingest.db"]

    def get_row(self, data, used_in):
        return [
            data.get("label", ""),
            data.get("host", ""),
            str(data.get("port", "")),
            data.get("username", ""),
            data.get("database", ""),
            data.get("default_channel", ""),
            data.get("serial", ""),
        ]

    def get_conn_id(self, cid, data):
        return cid
