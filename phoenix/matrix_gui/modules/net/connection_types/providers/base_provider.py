from abc import ABC, abstractmethod

class ConnectionProviderInterface(ABC):
    """
    Provider is responsible for:
    - Table column definitions
    - How a row is displayed
    - How conn_id is chosen
    """
    SENSITIVE_KEYS = {"password", "token", "api_key", "bot_token", "secret", "webhook_url"}

    @abstractmethod
    def get_columns(self) -> list[str]:
        pass

    @abstractmethod
    def get_row(self, data: dict, used_in: list[str]) -> list[str]:
        pass

    @abstractmethod
    def get_conn_id(self, conn_id: str, data: dict) -> str:
        pass

    @abstractmethod
    def get_default_channel_options(self) -> list[str]:
        """Return allowed default channels for this protocol."""
        pass

    def mask_if_sensitive(self, key, value):
        if key.lower() in self.SENSITIVE_KEYS:
            return self.mask_sensitive(value)
        return value

    def mask_sensitive(self, value: str):
        if not value:
            return ""
        if len(value) <= 4:
            return "****"
        return value[:2] + "••••••••••" + value[-2:]