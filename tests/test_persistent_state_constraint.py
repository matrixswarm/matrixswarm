"""Contract tests for Phoenix-backed persistent agent journals."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDITOR = (
    ROOT
    / "phoenix/matrix_gui/registry/object_classes/editors/persistent_state.py"
)
PROVIDER = (
    ROOT
    / "phoenix/matrix_gui/registry/object_classes/providers/persistent_state.py"
)
META = ROOT / "phoenix/agents_meta/forensic_detective.json"
AGENT = (
    ROOT
    / "matrixos/agents/python_core/forensic_detective/forensic_detective.py"
)


class PersistentStateConstraintTests(unittest.TestCase):
    def test_registry_components_compile_and_keep_key_out_of_list_row(self):
        editor = EDITOR.read_text(encoding="utf-8")
        provider = PROVIDER.read_text(encoding="utf-8")
        compile(editor, str(EDITOR), "exec")
        compile(provider, str(PROVIDER), "exec")

        self.assertIn('"config/security/persistent_state"', editor)
        self.assertIn('"sensitive_fields": {"key": "1"}', editor)
        self.assertIn('self.key.setEchoMode(QLineEdit.EchoMode.Password)', editor)
        self.assertIn("self._lock_persisted_identity()", editor)
        self.assertNotIn('data.get("key"', provider)

    def test_forensic_detective_requires_and_uses_encrypted_journal(self):
        metadata = json.loads(META.read_text(encoding="utf-8"))
        constraints = [next(iter(item)) for item in metadata["constraints"]]
        self.assertIn("persistent_state", constraints)

        source = AGENT.read_text(encoding="utf-8")
        self.assertIn("class Agent(EncryptedStateMixin, BootAgent):", source)
        self.assertIn(
            'self.init_encrypted_state(namespace="forensic_journal")', source
        )
        self.assertIn("self.verify_existing_journal()", source)
        self.assertIn("self.load_encrypted_state(", source)
        self.assertIn("authenticated latest incident", source)
        self.assertIn("self.save_encrypted_state(", source)
        self.assertNotIn("json.dump(summary_data", source)


if __name__ == "__main__":
    unittest.main()
