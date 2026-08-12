import ipaddress


class IPUtils:
    """Utility class for IP address validation."""

    @staticmethod
    def validate_ip(ip: str) -> bool:
        """
        Validate if a given string is a valid IPv4 or IPv6 address.

        Args:
            ip (str): The IP address to validate.

        Returns:
            bool: True if valid, False otherwise.
        """
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

