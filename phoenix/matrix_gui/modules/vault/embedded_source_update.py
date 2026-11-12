"""Atomically update one embedded agent in a saved encrypted directive."""

import base64
import binascii
import hashlib
import hmac
import json
import re

from matrix_gui.modules.vault.crypto.deploy_tools import (
    decrypt_swarm_encrypted_directive,
    encrypt_data,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SOURCE = 16 * 1024 * 1024


class EmbeddedSourceUpdateError(RuntimeError):
    """A safe, non-secret reason an embedded update was refused."""


def bundle_fingerprint(bundle):
    return hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def embedded_source_transform(deployment_id, expected_bundle_hash, agent_id, encoded_source, expected_source_hash):
    """Build a pure detached-section transform for the serialized vault writer."""
    if (not isinstance(deployment_id, str) or not deployment_id
            or not isinstance(agent_id, str) or not agent_id
            or not isinstance(expected_bundle_hash, str) or not _SHA256.fullmatch(expected_bundle_hash)
            or not isinstance(expected_source_hash, str) or not _SHA256.fullmatch(expected_source_hash)
            or not isinstance(encoded_source, str) or len(encoded_source) > ((_MAX_SOURCE + 2) // 3) * 4):
        raise EmbeddedSourceUpdateError("INVALID_REQUEST")
    def transform(deployments):
        try:
            source = base64.b64decode(encoded_source, validate=True)
            if not source or len(source) > _MAX_SOURCE:
                raise ValueError("empty or oversized source")
            source.decode("utf-8")
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise EmbeddedSourceUpdateError("INVALID_SOURCE") from exc
        digest = hashlib.sha256(source).hexdigest()
        if not hmac.compare_digest(digest, expected_source_hash):
            raise EmbeddedSourceUpdateError("SOURCE_MISMATCH")
        if not isinstance(deployments, dict) or not isinstance(deployments.get(deployment_id), dict):
            raise EmbeddedSourceUpdateError("DEPLOYMENT_MISSING")
        record = deployments[deployment_id]
        bundle, key = record.get("encrypted_bundle"), record.get("swarm_key")
        if not isinstance(bundle, dict) or not isinstance(key, str):
            raise EmbeddedSourceUpdateError("DIRECTIVE_UNAVAILABLE")
        if not hmac.compare_digest(bundle_fingerprint(bundle), expected_bundle_hash):
            raise EmbeddedSourceUpdateError("DEPLOYMENT_CHANGED")
        try:
            key_bytes = base64.b64decode(key, altchars=b"-_", validate=True)
            if len(key_bytes) != 32:
                raise ValueError("invalid swarm key")
            directive = decrypt_swarm_encrypted_directive(bundle, key)
        except Exception as exc:
            raise EmbeddedSourceUpdateError("DIRECTIVE_UNAVAILABLE") from exc
        matches = []

        def visit(node):
            if not isinstance(node, dict):
                raise EmbeddedSourceUpdateError("INVALID_DIRECTIVE")
            if node.get("universal_id") == agent_id:
                matches.append(node)
            children = node.get("children", [])
            if not isinstance(children, list):
                raise EmbeddedSourceUpdateError("INVALID_DIRECTIVE")
            for child in children:
                visit(child)

        root = directive.get("agent_tree", directive) if isinstance(directive, dict) else directive
        visit(root)
        if len(matches) != 1:
            raise EmbeddedSourceUpdateError("AGENT_NOT_UNIQUE")
        node = matches[0]
        if "src_embed" not in node:
            raise EmbeddedSourceUpdateError("SOURCE_NOT_EMBEDDED")
        if node.get("lang", "python") != "python":
            raise EmbeddedSourceUpdateError("UNSUPPORTED_LANGUAGE")
        node["src_embed"] = encoded_source
        node["hash_bang"] = digest
        updated_bundle = encrypt_data(json.dumps(directive, indent=2).encode("utf-8"), key_bytes)
        record["encrypted_bundle"] = updated_bundle
        record["encrypted_hash"] = bundle_fingerprint(updated_bundle)
        return deployments

    return transform


def update_embedded_source(vault, deployment_id, expected_bundle_hash, agent_id, encoded_source, expected_source_hash):
    """Synchronous adapter for callers that do not run on a GUI thread."""
    transform = embedded_source_transform(deployment_id, expected_bundle_hash, agent_id, encoded_source, expected_source_hash)
    if not vault.transform_section("deployments", transform):
        raise EmbeddedSourceUpdateError("SAVE_FAILED")
    return expected_source_hash
