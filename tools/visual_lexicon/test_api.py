import unittest
import json
import zlib
from tools.visual_lexicon.api import encode, decode, ConceptRegistry, validate_token_data, hash_token

class TestVisualLexiconAPI(unittest.TestCase):

    def get_valid_token(self):
        return {
            "version": "1.0.0",
            "viewBox": "0 0 24 24",
            "paths": [
                "<path d='M12 2L2 22h20L12 2z' fill='#000'/>"
            ],
            "palette": ["#000"],
            "semantic_label": "triangle",
            "source_evidence": {
                "source_id": "fixture_source_1",
                "origin_url": "https://example.com/fixture1",
                "publisher": "Test Publisher",
                "dataset_version": "1.0",
                "retrieval": {
                    "identity": "test_identity",
                    "url": "https://example.com/fixture1",
                    "date": "2023-01-01",
                    "artifact_path": "path/to/artifact",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                },
                "license": {
                    "id": "CC0-1.0",
                    "evidence_url": "https://example.com/license",
                    "evidence_path": "path/to/license",
                    "evidence_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                },
                "status": "APPROVED_FOR_REDISTRIBUTION",
                "alterations": ["optimized"]
            }
        }

    def test_invalid_license(self):
        token = self.get_valid_token()
        token["source_evidence"]["license"]["id"] = "CC-BY-SA-4.0"
        with self.assertRaises(ValueError) as context:
            encode(token)
        self.assertIn("Asset must be explicitly licensed under CC0-1.0", str(context.exception))

    def test_valid_encode_decode(self):
        token = self.get_valid_token()
        compressed, h = encode(token)
        self.assertLess(len(compressed), 2048)
        decoded = decode(compressed)
        self.assertEqual(decoded, token)

    def test_concept_registry_valid(self):
        registry = ConceptRegistry()
        registry.register("concept_1", "hash_abc")
        registry.register("concept_1", "hash_abc") # Should not raise
        registry.register("concept_2", "hash_def")
        self.assertEqual(registry.mappings["concept_1"], "hash_abc")
        self.assertEqual(registry.mappings["concept_2"], "hash_def")

    def test_concept_registry_collision(self):
        registry = ConceptRegistry()
        registry.register("concept_1", "hash_abc")
        with self.assertRaises(ValueError) as context:
            registry.register("concept_1", "hash_def")
        self.assertIn("Concept identity collision", str(context.exception))

    def test_oversized_token(self):
        token = self.get_valid_token()
        # Make paths huge, needs to be highly uncompressible to trigger 2048 size limit
        import random
        import string
        huge_uncompressible_string = ''.join(random.choices(string.ascii_letters + string.digits, k=5000))
        token["paths"] = [f"<path d='{huge_uncompressible_string}' fill='#000'/>"]

        with self.assertRaises(ValueError) as context:
            encode(token)
        self.assertIn("Compressed token exceeds 2048 bytes limit", str(context.exception))

    def test_too_many_paths(self):
        token = self.get_valid_token()
        token["paths"] = ["<path/>"] * 50
        with self.assertRaises(ValueError) as context:
            encode(token)
        self.assertIn("Paths must be a list with fewer than 50 items", str(context.exception))

    def test_missing_fields(self):
        token = self.get_valid_token()
        del token["version"]
        with self.assertRaises(ValueError) as context:
            encode(token)
        self.assertIn("Missing required field: version", str(context.exception))

    def test_malicious_geometry(self):
        token = self.get_valid_token()
        token["paths"].append("<script>alert(1)</script>")
        with self.assertRaises(ValueError) as context:
            encode(token)
        self.assertIn("Malicious content found in paths", str(context.exception))

        token = self.get_valid_token()
        token["paths"].append("javascript:alert(1)")
        with self.assertRaises(ValueError) as context:
            encode(token)
        self.assertIn("Malicious content found in paths", str(context.exception))
