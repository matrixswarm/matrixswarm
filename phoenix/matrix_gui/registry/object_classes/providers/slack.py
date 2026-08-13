from .base_provider import ConnectionProvider

class Slack(ConnectionProvider):

    def get_columns(self):
        return ["Label", "Webhook URL", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["alerts"]

    def get_row(self, data):
        url = data.get("webhook_url","")
        preview = url[:28] + "…" if len(url) > 32 else url
        return [
            data.get("label",""),
            preview,
            data.get("default_channel",""),
            data.get("serial",""),
        ]

    def get_conn_id(self, cid, data):
        return cid
