import re

class KeyValidator:
    """Utility class to validate SSH private keys."""

    @staticmethod
    def validate_private_key(private_key: str) -> bool:
        """
        Validate the format of an SSH private key.

        Args:
            private_key (str): The SSH private key to validate.

        Returns:
            bool: True if the key appears valid, False otherwise.

        Note:
            This implementation performs basic validation to check if the key is
            properly formatted. It does NOT verify the cryptographic accuracy.
        """
        if not private_key:
            return False

        # Basic check for start and end markers of an SSH private key
        private_key_pattern = re.compile(
            r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]+-----END (?:[A-Z]+ )?PRIVATE KEY-----"
        )
        return bool(private_key_pattern.fullmatch(private_key.strip()))
