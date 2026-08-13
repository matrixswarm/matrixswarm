from .base_provider import ConnectionProvider

class WSS(ConnectionProvider):

    def get_columns(self):
        return ["Label", "Host", "Port", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["payload.reception"]

    def get_row(self, data):
        return [
            data.get("label",""),
            data.get("host",""),
            str(data.get("port","")),
            data.get("default_channel",""),
            data.get("serial",""),
        ]

    def get_conn_id(self, cid, data):
        return cid
