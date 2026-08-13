from .base_provider import ConnectionProviderInterface

class Discord(ConnectionProviderInterface):

    def get_columns(self):
        return ["Label", "Channel ID", "Bot Token", "Default Channel", "Serial"]

    def get_default_channel_options(self):
        return ["alerts", "outgoing.command"]

    def get_row(self, data, used_in):
        label = data.get("label", "")
        channel = data.get("channel_id", "")
        bot_token = self.mask_sensitive(data.get("bot_token", ""))
        def_chan = data.get("default_channel", "")
        serial = data.get("serial", "")[:8] + "..."
        return [label, channel, bot_token, def_chan, serial]

    def get_conn_id(self, cid, data):
        return cid