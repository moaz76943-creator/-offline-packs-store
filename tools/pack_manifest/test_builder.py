import unittest
from pathlib import Path
import json
import gzip
import base64
import tempfile
import os

from tools.pack_manifest.builder import build_manifest, generate_update_plan, is_safe_path

class TestBuilder(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def test_update_plan_identical_versions(self):
        old = {"packs": [{"packId": "en", "version": "1.0", "contentSha256": "abc"}]}
        new = {"packs": [{"packId": "en", "version": "1.0", "contentSha256": "abc"}]}
        plan = generate_update_plan(old, new)
        self.assertEqual(plan["unchanged"], ["en"])
        self.assertEqual(plan["updated"], [])

    def test_update_plan_changed_bytes(self):
        old = {"packs": [{"packId": "en", "version": "1.0", "contentSha256": "abc"}]}
        new = {"packs": [{"packId": "en", "version": "1.1", "contentSha256": "def"}]}
        plan = generate_update_plan(old, new)
        self.assertEqual(plan["unchanged"], [])
        self.assertEqual(plan["updated"], ["en"])

    def test_update_plan_skip_unchanged_payload(self):
        old = {"packs": [{"packId": "en", "version": "1.0", "contentSha256": "abc"}]}
        new = {"packs": [{"packId": "en", "version": "1.1", "contentSha256": "abc"}]}
        plan = generate_update_plan(old, new)
        self.assertEqual(plan["unchanged"], ["en"])
        self.assertEqual(plan["updated"], [])

    def test_update_plan_added_assets(self):
        old = {"packs": []}
        new = {"packs": [{"packId": "en", "version": "1.0", "contentSha256": "abc"}]}
        plan = generate_update_plan(old, new)
        self.assertEqual(plan["added"], ["en"])

    def test_update_plan_removed_packs(self):
        old = {"packs": [{"packId": "en", "version": "1.0", "contentSha256": "abc"}]}
        new = {"packs": []}
        plan = generate_update_plan(old, new)
        self.assertEqual(plan["removed"], ["en"])

    def test_update_plan_broken_dependencies(self):
        old = {"packs": []}
        new = {"packs": [{"packId": "en", "version": "1.0", "contentSha256": "abc", "dependencies": ["semantic-vectors"]}]}
        plan = generate_update_plan(old, new)
        self.assertEqual(plan["broken_dependencies"], [{"pack": "en", "missing_dependency": "semantic-vectors"}])

    def test_reject_untrusted_paths(self):
        self.assertTrue(is_safe_path(self.root / "safe", self.root))
        self.assertFalse(is_safe_path(self.root / "../unsafe", self.root))
        with self.assertRaises(ValueError):
             build_manifest("en", self.root / "../unsafe", self.root)

    def test_build_manifest(self):
        # We need to construct a valid envelope to test build_manifest
        manifest = {
            "packId": "en",
            "languageCode": "en",
            "version": "1.0",
            "schemaVersion": "2.0.0",
            "contentRows": 10,
            "contentSha256": "abc",
            "sourceIds": ["test-source"],
            "licenses": ["CC0"]
        }

        content = {
            'metadata/pack.json': json.dumps(manifest).encode(),
            'content/content.json': json.dumps({'tableCounts': {'lexicon': 10}, 'licenses': ["CC0"]}).encode(),
            'content/content.sqlite': b''
        }

        envelope = {
            "schemaVersion": "2.0.0",
            "files": [
                {"path": p, "contentBase64": base64.b64encode(c).decode('ascii')}
                for p, c in content.items()
            ]
        }

        pack_path = self.root / "en.pack.gz"
        with gzip.open(pack_path, "wt") as f:
            json.dump(envelope, f)

        res = build_manifest("en", pack_path, self.root)
        self.assertEqual(res["packId"], "en")
        self.assertEqual(res["contentRows"], 10)
        self.assertEqual(res["licenses"], ["CC0"])

    def test_create_manifest(self):
        # Create mock packs
        manifest_en = {
            "packId": "en",
            "languageCode": "en",
            "version": "1.0.0",
            "schemaVersion": "2.0.0",
            "contentRows": 10,
            "contentSha256": "abc",
            "sourceIds": ["test-source"],
            "licenses": ["CC0"]
        }
        content_en = {
            'metadata/pack.json': json.dumps(manifest_en).encode(),
            'content/content.json': json.dumps({'tableCounts': {'lexicon': 10}}).encode(),
            'content/content.sqlite': b''
        }
        envelope_en = {
            "schemaVersion": "2.0.0",
            "files": [
                {"path": p, "contentBase64": base64.b64encode(c).decode('ascii')}
                for p, c in content_en.items()
            ]
        }

        pack_path = self.root / "en-1.0.0.pack.gz"
        with gzip.open(pack_path, "wt") as f:
            json.dump(envelope_en, f)

        output_file = self.root / "manifest.json"

        from tools.pack_manifest.builder import create_manifest
        create_manifest(self.root, output_file)

        with output_file.open('r') as f:
            data = json.load(f)
            self.assertEqual(len(data["packs"]), 1)
            self.assertEqual(data["packs"][0]["packId"], "en")
            self.assertEqual(data["packs"][0]["contentRows"], 10)

if __name__ == '__main__':
    unittest.main()
