import unittest
import tempfile
import shutil
from pathlib import Path
from tools.visual_lexicon.encoder import VisualTokenEncoder
from tools.visual_lexicon.decoder import VisualTokenDecoder
import json
from tools.visual_lexicon.api import VisualLexiconAPI
from tools.visual_lexicon.validator import VisualTokenValidator

class TestVisualLexicon(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.encoder = VisualTokenEncoder(output_dir=self.test_dir)
        self.decoder = VisualTokenDecoder()
        self.api = VisualLexiconAPI(manifest_path=Path(self.test_dir) / "manifest.json")
        self.validator = VisualTokenValidator()

        self.valid_token = {
            "version": 1,
            "concept_id": "concept_123",
            "semantic_label": "A red circle",
            "alt_text": "Red circle icon",
            "source": {
                "author": "Test Author",
                "license": "CC0-1.0"
            },
            "viewBox": "0 0 100 100",
            "palette": ["#FF0000"],
            "paths": [
                {
                    "d": "M 50 0 A 50 50 0 1 0 50 100 A 50 50 0 1 0 50 0 Z",
                    "fill": "#FF0000"
                }
            ]
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_encode_decode_roundtrip(self):
        # Encode
        token_hash, output_path = self.encoder.encode(self.valid_token)
        self.assertTrue(output_path.exists())

        # Decode
        decoded_token = self.decoder.decode(output_path)
        self.assertEqual(decoded_token, self.valid_token)

    def test_fixtures_roundtrip(self):
        fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        for fixture_file in fixtures_dir.glob("*.json"):
            with open(fixture_file, 'r', encoding='utf-8') as f:
                fixture_token = json.load(f)

            token_hash, output_path = self.encoder.encode(fixture_token)
            self.assertTrue(output_path.exists())

            decoded_token = self.decoder.decode(output_path)
            self.assertEqual(decoded_token, fixture_token)

    def test_oversized_asset_rejected(self):
        # Create multiple long paths that will compress to > 2048 bytes
        # but individually remain under the 2048 character limit per path
        # and under the 100 paths limit.
        long_path = "M 0 0 " + "L 1 1 " * 300  # length ~ 1800 chars
        oversized_token = self.valid_token.copy()
        # 50 paths * ~1800 chars is ~90,000 chars, highly compressible but
        # should easily exceed 2048 bytes even after zlib.
        # We need a string with more entropy to defeat zlib compression.
        import random
        random.seed(42)

        paths = []
        for _ in range(50):
            # Generate somewhat random coordinates to reduce zlib ratio
            d = "M 0 0 " + " ".join([f"L {random.randint(0, 100)} {random.randint(0, 100)}" for _ in range(150)])
            paths.append({"d": d, "fill": "#000000"})

        oversized_token['paths'] = paths

        with self.assertRaisesRegex(ValueError, "exceeds limit of 2048 bytes"):
            self.encoder.encode(oversized_token)

    def test_malicious_script_injection_rejected(self):
        malicious_token = self.valid_token.copy()
        # Adding `<script>` in the path data
        malicious_token['paths'] = [{"d": "M 0 0 L 1 1 <script>alert(1)</script>", "fill": "#000000"}]

        with self.assertRaises(ValueError):
            self.encoder.encode(malicious_token)

    def test_invalid_license_rejected(self):
        invalid_license_token = self.valid_token.copy()
        # Needs to be a deep copy for nested source
        invalid_license_token['source'] = {
            "author": "Thief",
            "license": "Copyrighted"
        }

        with self.assertRaises(ValueError):
            self.encoder.encode(invalid_license_token)

    def test_api_manifest_registration(self):
        token_hash, _ = self.encoder.encode(self.valid_token)
        self.api.register_token(self.valid_token['concept_id'], token_hash)

        # Retrieve
        retrieved_hash = self.api.get_token_hash(self.valid_token['concept_id'])
        self.assertEqual(retrieved_hash, token_hash)

        # Test collision mapping rejection
        other_valid_token = self.valid_token.copy()
        other_valid_token['semantic_label'] = "A blue circle"
        other_valid_token['palette'] = ["#0000FF"]
        other_valid_token['paths'] = [{"d": "M 50 0 A 50 50 0 1 0 50 100 A 50 50 0 1 0 50 0 Z", "fill": "#0000FF"}]

        other_hash, _ = self.encoder.encode(other_valid_token)

        with self.assertRaises(ValueError):
            self.api.register_token(self.valid_token['concept_id'], other_hash)

    def test_deterministic_hashing(self):
        hash1, _ = self.encoder.encode(self.valid_token)
        hash2, _ = self.encoder.encode(self.valid_token)
        self.assertEqual(hash1, hash2)

    def test_max_path_count(self):
        many_paths_token = self.valid_token.copy()
        many_paths_token['paths'] = [{"d": "M 0 0 L 1 1"} for _ in range(101)]
        with self.assertRaises(ValueError):
            self.encoder.encode(many_paths_token)

if __name__ == '__main__':
    unittest.main()
