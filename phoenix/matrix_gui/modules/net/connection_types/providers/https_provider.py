from .base_provider import ConnectionProviderInterface

class HTTPS(ConnectionProviderInterface):

    def get_columns(self):
        return ["Label", "Host", "Port", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["outgoing.command"]

    def get_row(self, data, used_in):
        return [
            data.get("label",""),
            data.get("host",""),
            str(data.get("port","")),
            data.get("default_channel",""),
            data.get("serial",""),
        ]

    def get_conn_id(self, cid, data):
        return cid
