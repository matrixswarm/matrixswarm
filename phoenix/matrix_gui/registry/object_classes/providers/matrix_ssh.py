from .base_provider import ConnectionProvider


class MatrixSSH(ConnectionProvider):
    def get_columns(self):
        return ["Label", "SSH Profile", "Channel", "Primary", "Serial"]

    def get_default_channel_options(self):
        return ["outgoing.command"]

    def get_row(self, data):
        return [str(data.get(key, "")) for key in
                ("label", "ssh_serial", "channel", "default_outgoing", "serial")]

    def get_conn_id(self, cid, data):
        return cid
