"""Phoenix receive route using an existing pinned SSH Registry credential."""

from .matrix_ssh import MatrixSSH


class MatrixSSHEgress(MatrixSSH):
    channel_name = "payload.reception"
    primary_field = "default_payload_reception"
    primary_label = "Primary Incoming Transport"

    def deploy_fields(self):
        fields = super().deploy_fields()
        fields["proto"] = "ssh_egress"
        return fields
