class ProtocolUtils:
    """Utility class for protocol validation."""

    @staticmethod
    def validate_protocol(protocol: str, required_protocol: str = "https") -> bool:
        """
        Validate if the given protocol matches the required protocol.

        Args:
            protocol (str): The protocol to validate (e.g., "http", "https").
            required_protocol (str): The required protocol to match (default is "https").

        Returns:
            bool: True if the protocol matches the required protocol, False otherwise.
        """
        return protocol.strip().lower() == required_protocol.strip().lower()
