class PortUtils:
    """Utility class for port validation."""

    @staticmethod
    def validate_port(port: str, min_value: int = 1, max_value: int = 65535) -> bool:
        """
        Validate if the given port is numeric and within the valid range.

        Args:
            port (str): The port value to validate (as a string).
            min_value (int): The minimum valid port number (default: 1).
            max_value (int): The maximum valid port number (default: 65535).

        Returns:
            bool: True if the port is valid, False otherwise.
        """
        if not port.isdigit():
            return False

        numeric_port = int(port)
        return min_value <= numeric_port <= max_value
