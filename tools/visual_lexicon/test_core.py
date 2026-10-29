import unittest
from tools.visual_lexicon.core import encode_token, decode_token, get_content_hash
from tools.visual_lexicon.schema import validate_manifest

class TestVisualLexicon(unittest.TestCase):
    def test_encode_decode_valid(self):
        token_data = {
            "version": 1,
            "viewBox": [0, 0, 24, 24],
            "paths": ["M12 2L2 22h20L12 2z"],
            "palette": ["#000000"],
            "semantic_label": "triangle"
        }
        encoded = encode_token(token_data)
        self.assertTrue(len(encoded) < 2048)
        decoded = decode_token(encoded)
        self.assertEqual(decoded, token_data)

    def test_encode_token(self):
        token_data = {
            "version": 1,
            "viewBox": [0, 0, 24, 24],
            "paths": ["M12 2L2 22h20L12 2z"],
            "palette": ["#000000"],
            "semantic_label": "triangle"
        }
        encoded = encode_token(token_data)
        self.assertIsInstance(encoded, bytes)
        self.assertTrue(len(encoded) < 2048)

    def test_decode_token(self):
        token_data = {
            "version": 1,
            "viewBox": [0, 0, 24, 24],
            "paths": ["M12 2L2 22h20L12 2z"],
            "palette": ["#000000"],
            "semantic_label": "triangle"
        }
        encoded = encode_token(token_data)
        decoded = decode_token(encoded)
        self.assertEqual(decoded, token_data)

    def test_oversized_token(self):
        token_data = {
            "version": 1,
            "viewBox": [0, 0, 24, 24],
            "paths": ["M0 0L1 1 " * 200], # very long path, coordinate limit is 500
            "palette": ["#000000"],
            "semantic_label": "complex"
        }
        with self.assertRaises(ValueError):
            encode_token(token_data) # wait, limit is 2048 compressed or coordinates limit

    def test_manifest_validation(self):
        manifest = {
            "concept_id": "concept.en.triangle",
            "author": "Alice",
            "source": "https://example.com/triangle.svg",
            "license": "CC0"
        }
        self.assertTrue(validate_manifest(manifest))

        manifest["license"] = "Copyrighted"
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_missing_fields_manifest(self):
        manifest = {
            "concept_id": "concept.en.triangle",
            "author": "Alice"
        }
        with self.assertRaises(ValueError):
            validate_manifest(manifest)
