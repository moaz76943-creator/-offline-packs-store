import unittest
import json
import os
from tools.visual_lexicon.core import encode_token, decode_token
from tools.visual_lexicon.schema import validate_manifest

class TestFixtures(unittest.TestCase):
    def test_fixtures(self):
        # Determine path dynamically
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        fixture_path = os.path.join(base_dir, "media", "semantic_icons", "fixture.json")
        manifest_path = os.path.join(base_dir, "media", "semantic_icons", "manifest.json")

        with open(fixture_path, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        # Test valid manifest
        self.assertTrue(validate_manifest(manifest_data))

        # Test encode and decode roundtrip
        encoded = encode_token(token_data)
        self.assertTrue(len(encoded) < 2048)
        decoded = decode_token(encoded)
        self.assertEqual(decoded, token_data)
