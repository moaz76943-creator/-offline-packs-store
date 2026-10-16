"""Read-only syntax/fixture verification; never import side-effectful root generators."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("setup_repo.py", "update_pack.py", "upgrade_public_store.py")


class LegacyFixtureDeduplicationTests(unittest.TestCase):
    def test_single_shared_dummy_image_constant(self):
        module = ast.parse((ROOT / "utils.py").read_text(encoding="utf-8"))
        values = [
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "dummy_webp" for t in node.targets)
        ]
        self.assertEqual(len(values), 1)
        self.assertIsInstance(values[0], bytes)
        self.assertTrue(values[0].startswith(b"RIFF"))
        self.assertIn(b"WEBP", values[0][:16])

    def test_all_legacy_generators_import_same_constant(self):
        for name in SCRIPTS:
            with self.subTest(name=name):
                tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
                self.assertTrue(any(
                    isinstance(node, ast.ImportFrom)
                    and node.module == "utils"
                    and any(alias.name == "dummy_webp" for alias in node.names)
                    for node in tree.body
                ))
                self.assertFalse(any(
                    isinstance(node, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "dummy_webp"
                        for t in node.targets
                    ) for node in tree.body
                ))

    def test_static_inspection_does_not_execute_generators(self):
        for name in SCRIPTS:
            with self.subTest(name=name):
                self.assertIsInstance(
                    ast.parse((ROOT / name).read_text(encoding="utf-8")), ast.Module
                )


if __name__ == "__main__":
    unittest.main()
