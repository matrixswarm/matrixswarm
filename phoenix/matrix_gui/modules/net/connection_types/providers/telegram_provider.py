from .base_provider import ConnectionProviderInterface

class Telegram(ConnectionProviderInterface):

    def get_columns(self):
        return ["Label", "Chat ID", "Token", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["alerts"]

    def get_row(self, data, used_in):
        preview = (data.get("bot_token","")[:6] + "…") if data.get("bot_token") else ""
        return [
            data.get("label",""),
            data.get("chat_id",""),
            preview,
            data.get("default_channel",""),
            data.get("serial",""),
        ]

    def get_conn_id(self, cid, data):
        return cid
