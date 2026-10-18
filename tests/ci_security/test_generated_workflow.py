"""Prevent legacy generator from restoring an unsafe GitHub JSON workflow.

Never import or execute perfect_public_store.py: its top-level code writes
manifests and pack bytes. Inspect only the static source template.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "perfect_public_store.py"
WORKFLOW = ROOT / ".github/workflows/validate_json.yml"


def literal_workflow_template():
    module = ast.parse(GENERATOR.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "github_action_yml"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Static github_action_yml template missing")


class GeneratedJsonWorkflowSecurityTests(unittest.TestCase):
    def test_generator_keeps_current_secure_workflow_exactly(self):
        self.assertEqual(
            literal_workflow_template().strip(),
            WORKFLOW.read_text(encoding="utf-8").strip(),
        )

    def test_generator_never_interpolates_filename_into_shell_code(self):
        template = literal_workflow_template()
        self.assertNotIn('xargs -0 -I {} bash -c', template)
        self.assertIn('jq empty "$1"', template)
        self.assertIn("xargs -0 -r -n 1 sh -c", template)

    def test_inspection_has_no_generator_side_effect(self):
        self.assertTrue(GENERATOR.is_file())
        self.assertTrue(WORKFLOW.is_file())
        self.assertIn("on: [push, pull_request]", literal_workflow_template())


if __name__ == "__main__":
    unittest.main()
