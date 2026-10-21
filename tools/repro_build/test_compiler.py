import json
import tempfile
import unittest
from pathlib import Path
from tools.repro_build.compiler import ReproBuilder

class TestReproBuilder(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.workspace = Path(self.d.name)
        self.repo_root = Path(__file__).resolve().parents[2]
        self.builder = ReproBuilder(self.workspace, self.repo_root)

        self.valid_doc = {
            "contract_version": "1.0.0",
            "document_id": "test_doc_1",
            "lexemes": [{
                "lexeme_id": "l1-id",
                "language": "de",
                "surface": "test",
                "lemma": "test",
                "pos": "noun",
                "direction": "ltr",
                "script": "Latn",
                "source": {
                    "source_id": "test_src",
                    "origin_url":"https://example.org/fixtures-only",
                    "publisher":"Self-authored synthetic test",
                    "dataset_version":"1",
                    "retrieval_id":"synthetic:1",
                    "license_id":"LicenseRef-SyntheticTestFixture",
                    "record_locator":"illustration",
                    "publication_approved":False,
                    "fixture_only":True,
                    "artifact_sha256":None
                }
            }],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }

    def test_build_empty_source(self):
        src = self.workspace / "de.json"
        with open(src, "w") as f:
            json.dump({
                "contract_version": "1.0.0",
                "document_id": "test_doc_1",
                "lexemes": [],
                "senses": [],
                "translations": [],
                "examples": [],
                "relations": []
            }, f)

        with self.assertRaisesRegex(RuntimeError, "source language does not match"):
            self.builder.build(src, "de", fixture_only=True)

    def test_changed_manifest(self):
        src = self.workspace / "de.json"
        with open(src, "w") as f:
            json.dump(self.valid_doc, f)

        output1 = self.builder.build(src, "de", fixture_only=True)

        # Change manifest (lexical record)
        modified_doc = self.valid_doc.copy()
        modified_doc["document_id"] = "test_doc_2"
        with open(src, "w") as f:
            json.dump(modified_doc, f)

        output2 = self.builder.build(src, "de", fixture_only=True)

        # Verify the outputs are different files (content-addressed)
        self.assertNotEqual(output1, output2)

    def test_malformed_records(self):
        src = self.workspace / "de.json"
        with open(src, "w") as f:
            json.dump({"contract_version": "1.0.0"}, f) # Missing required fields

        with self.assertRaises(ValueError):
            self.builder.build(src, "de", fixture_only=True)

    def test_deterministic_repeated_builds(self):
        src = self.workspace / "de.json"
        with open(src, "w") as f:
            json.dump(self.valid_doc, f)

        output1 = self.builder.build(src, "de", fixture_only=True)
        output2 = self.builder.build(src, "de", fixture_only=True)

        self.assertEqual(output1, output2)

    def test_preserves_valid_artifacts_on_failure(self):
        src = self.workspace / "de.json"
        with open(src, "w") as f:
            json.dump(self.valid_doc, f)

        output = self.builder.build(src, "de", fixture_only=True)
        self.assertTrue(output.exists())

        # Corrupt the source
        with open(src, "w") as f:
            json.dump({"invalid": "doc"}, f)

        with self.assertRaises(ValueError):
            self.builder.build(src, "de", fixture_only=True)

        self.assertTrue(output.exists())

    def test_invalid_license_rejection(self):
        # We simulate invalid licensing without fixture_only
        src = self.workspace / "de.json"
        with open(src, "w") as f:
            json.dump(self.valid_doc, f)

        # Expecting compilation error due to no fixture_only flag with fake source
        with self.assertRaises(RuntimeError):
            self.builder.build(src, "de", fixture_only=False)

if __name__ == "__main__":
    unittest.main()
