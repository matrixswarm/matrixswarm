from .matrix_ssh import MatrixSSH


class MatrixSSHEgress(MatrixSSH):
    def get_default_channel_options(self):
        return ["payload.reception"]

    def get_row(self, data):
        return [str(data.get(key, "")) for key in
                ("label", "ssh_serial", "channel", "default_payload_reception", "serial")]
