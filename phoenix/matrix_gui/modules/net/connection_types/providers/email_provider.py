from .base_provider import ConnectionProviderInterface

class Email(ConnectionProviderInterface):

    def get_columns(self):
        return ["Label", "User", "Server", "Port", 'Encryption', "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["alerts"]

    def get_row(self, data, used_in):
        mode = data.get("type","outgoing")
        if mode == "outgoing":
            server = data.get("smtp_server","")
            port = data.get("smtp_port","")
            user = data.get("smtp_username","")
            encryption = data.get("smtp_encryption", "")
        else:
            server = data.get("incoming_server","")
            port = data.get("incoming_port","")
            user = data.get("incoming_username","")
            encryption=data.get("incoming_encryption", "")
        return [
            data.get("label",""),
            user,
            server,
            str(port),
            encryption,
            data.get("default_channel",""),
            data.get("serial",""),
        ]

    def get_conn_id(self, cid, data):
        return cid
