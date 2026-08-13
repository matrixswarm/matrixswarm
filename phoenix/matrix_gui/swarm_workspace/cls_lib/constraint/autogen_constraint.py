# Commander Edition – AutoGenConstraint
# Standard base for autogen constraint handlers.
# Path describes where bundle data belongs in the swarm directive.

from datetime import datetime
from abc import ABC, abstractmethod

class AutoGenConstraint(ABC):
    """Base class for autogen constraint handlers."""

    # Where each type of constraint lives in DEPLOYMENT
    deploy_paths = {
        "packet_signing": ["signing"],
        "connection_cert": ["connection_cert"],
        "symmetric_encryption": ["symmetric_encryption"],
    }

    # Where each type of constraint lives in DIRECTIVE, leading "config" in the path is auto prepended
    directive_paths = {
        "packet_signing": ["security", "signing"],
        "connection_cert": ["security", "connection"],
        "symmetric_encryption": ["security", "symmetric_encryption"],
    }

    @staticmethod
    def get_path(category, scope="deploy"):
        if scope == "directive":
            return AutoGenConstraint.directive_paths.get(category, [])
        return AutoGenConstraint.deploy_paths.get(category, [])

    @staticmethod
    def set_nested(base: dict, path_parts: list, value):
        if not path_parts:
            return base
        node = base
        for part in path_parts[:-1]:
            node = node.setdefault(part, {})
        node[path_parts[-1]] = value
        return base


    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------
    @staticmethod
    def timestamp():
        return datetime.utcnow().isoformat() + "Z"

    def base_fields(self):
        return {"created_at": self.timestamp()}

    # ----------------------------------------------------------
    # Implemented by subclasses
    # ----------------------------------------------------------
    @abstractmethod
    def resolve(self, agent):
        """Return a dict with the fields for both directive and deployment."""
        pass

    def build_output(self, agent):
        """Return a unified structure with directive and deployment bundles."""
        bundle = self.resolve(agent)
        return {
            "category": self.category,
            "directive": {
                "path": self.get_path("directive"),
                "fields": bundle.get("directive", bundle)
            },
            "deploy": {
                "path": self.get_path("deploy"),
                "fields": bundle.get("deploy", bundle)
            }
        }
