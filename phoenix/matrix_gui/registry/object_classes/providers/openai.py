from .base_provider import ConnectionProvider

class OpenAI(ConnectionProvider):

    def get_columns(self):
        return ["Label", "API Key", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["oracle"]

    def get_row(self, data):
        preview = (data.get("api_key","")[:8] + "…") if data.get("api_key") else ""
        return [
            data.get("label",""),
            preview,
            data.get("default_channel",""),
            data.get("serial",""),
        ]

    def get_conn_id(self, cid, data):
        return cid
