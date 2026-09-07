from .base_provider import ConnectionProvider


class HarvesterAssignment(ConnectionProvider):
    """Registry list presentation for Harvester hive/SSH pairings."""

    def get_columns(self):
        return ["Label", "Hive", "SSH", "Authority", "Serial"]

    def get_default_channel_options(self):
        return ["harvester.observe"]

    def get_row(self, data):
        capability = data.get("capability", "contact_only")
        authority = (
            "Contact + resurrect"
            if capability == "contact_and_resurrect"
            else "Contact only"
        )
        return [
            str(data.get("label", "")),
            str(data.get("deployment_label", data.get("deployment_id", ""))),
            str(data.get("ssh_label", data.get("ssh_serial", ""))),
            authority,
            str(data.get("serial", "")),
        ]

    def get_conn_id(self, cid, data):
        return cid
