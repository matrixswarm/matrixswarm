from pathlib import Path
from contextlib import redirect_stdout
import io
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MATRIXOS = ROOT / "matrixos"
if str(MATRIXOS) not in sys.path:
    sys.path.insert(0, str(MATRIXOS))

from core.python_core.tree_parser import TreeParser


def source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class DynamicUniversalIdTests(unittest.TestCase):
    def test_dynamic_matrix_id_receives_root_keys_and_recovery_copy(self):
        matrix_uid = "1234567890abcdef1234567890abcdef"
        sentinel_uid = "abcdef1234567890abcdef1234567890"
        tree = {
            "name": "matrix",
            "universal_id": matrix_uid,
            "config": {},
            "children": [
                {
                    "name": "sentinel",
                    "universal_id": sentinel_uid,
                    "config": {"matrix_secure_verified": True},
                    "children": [],
                }
            ],
        }
        parser = TreeParser.load_tree_direct(tree)
        calls = []
        parser.assign_identity_token_to_node = lambda uid, *args, **kwargs: calls.append(
            (uid, kwargs)
        )

        with redirect_stdout(io.StringIO()):
            parser.assign_identity_to_all_nodes(
                object(),
                matrix_pub="matrix-public",
                matrix_priv="matrix-private",
                matrix_key_b64="matrix-aes",
                matrix_uid=matrix_uid,
            )

        self.assertEqual(calls[0][0], matrix_uid)
        self.assertEqual(calls[0][1]["replace_keys"]["priv_key"], "matrix-private")
        recovery = tree["children"][0]["config"]["matrix_secure_store"]
        self.assertEqual(recovery["matrix_node"]["universal_id"], matrix_uid)

    def test_root_id_is_propagated_and_literal_routes_are_removed(self):
        spawner = source("matrixos/core/python_core/core_spawner.py")
        boot = source("matrixos/core/python_core/boot_agent.py")
        matrixd = source("matrixos/scripts/matrixd")
        self.assertIn('"matrix": self.matrix_universal_id', spawner)
        self.assertIn("cp.set_matrix_universal_id(self.get_matrix_universal_id())", boot)
        self.assertIn("matrix_node = tp.nodes.get(MATRIX_UUID)", matrixd)
        self.assertIn('agent_name=matrix_node.get("name") or "matrix"', matrixd)
        self.assertNotIn(
            'cp.spawn_agent(universe, "site_boot", MATRIX_UUID, MATRIX_UUID',
            matrixd,
        )
        self.assertNotIn('"matrix": "matrix"', spawner)

        address_files = (
            "matrixos/agents/python_core/matrix_https/matrix_https.py",
            "matrixos/agents/python_core/matrix_email/matrix_email.py",
            "matrixos/agents/python_core/reaper/reaper.py",
            "matrixos/agents/python_core/scavenger/scavenger.py",
            "matrixos/agents/python_core/crypto_alert/crypto_alert.py",
        )
        for path in address_files:
            with self.subTest(path=path):
                self.assertNotIn('pass_packet(pk, "matrix")', source(path))

    def test_workspace_rotation_updates_exact_references(self):
        controller = source(
            "phoenix/matrix_gui/swarm_workspace/cls_lib/graph/"
            "tree_graph_controller.py"
        )
        inspector = source(
            "phoenix/matrix_gui/swarm_workspace/panels/agent_inspector/"
            "agent_inspector.py"
        )
        self.assertIn("def regenerate_all_universal_ids(self):", controller)
        self.assertIn("new_uid = uuid.uuid4().hex", controller)
        self.assertNotIn('new_uid = f"{prefix}-{uuid.uuid4().hex}"', controller)
        for field in ("connections", "params", "config", "constraints"):
            self.assertIn(f"node.{field} = self._replace_universal_id_references", controller)
        self.assertIn('QPushButton("Generate All UUIDs")', inspector)

    def test_phoenix_resolves_matrix_by_name_after_uuid_rotation(self):
        packet_security = source(
            "phoenix/matrix_gui/core/class_lib/packet_delivery/utility/"
            "security/packet_security.py"
        )
        outbound = source("phoenix/matrix_gui/core/dispatcher/outbound_dispatcher.py")
        agent_tree = source("phoenix/matrix_gui/core/panel/agent_tree/agent_tree.py")
        finalizer = source(
            "phoenix/matrix_gui/modules/directive/utils/directive_finalizer.py"
        )

        self.assertIn("def resolve_matrix_universal_id(deployment):", packet_security)
        self.assertIn('agent.get("name")', packet_security)
        self.assertIn("security_target_universal_id=None", outbound)
        self.assertIn('node.get("name")', agent_tree)
        self.assertIn("if not matrix_seen:", finalizer)

    def test_matrix_service_catalog_can_prime_from_master_tree(self):
        boot = source("matrixos/core/python_core/boot_agent.py")

        self.assertIn(
            'master = getattr(self, "_agent_tree_master", None)',
            boot,
        )
        self.assertIn(
            "master.get_minimal_services_tree(",
            boot,
        )
        self.assertIn(
            "self.get_matrix_universal_id()",
            boot,
        )


if __name__ == "__main__":
    unittest.main()
