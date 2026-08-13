from typing import Union
class Agent():
    def __init__(self):
        self._items = {}

    def add_item(self, keyword: str, data: dict):
        """Attach a dict under a keyword (overwrite if already exists)."""
        if not isinstance(data, dict):
            raise ValueError(f"Agent.add_item expects dict for '{keyword}', got {type(data)}")
        self._items[keyword] = data

    def has_item(self, keyword: str) -> bool:
        return keyword in self._items

    def get_item(self, keyword: str) -> dict:
        return self._items.get(keyword)

    def get_items(self) -> dict:
        return self._items

    @property
    def universal_id(self) -> Union[str, None]:
        """Shortcut to the core agent's universal_id (if present)."""
        if "agent" in self._items:
            return self._items["agent"].get("universal_id")
        return None

    @property
    def name(self) -> Union[str, None]:
        """Shortcut to the core agent's name (if present)."""
        if "agent" in self._items:
            return self._items["agent"].get("name")
        return None
