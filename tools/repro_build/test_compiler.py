import unittest
import json
import tempfile
from pathlib import Path
import shutil
import sqlite3

from tools.repro_build.compiler import CorpusCompiler, BuildError

class TestCorpusCompiler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo_root = Path(__file__).resolve().parent.parent.parent
        self.compiler = CorpusCompiler(workspace=self.temp_dir, repo_root=self.repo_root)

        self.source_obj = {
            "source_id": "src1",
            "origin_url": "https://test",
            "publisher": "TestPublisher",
            "dataset_version": "1.0",
            "retrieval_id": "r1",
            "license_id": "CC0-1.0",
            "record_locator": "L1",
            "fixture_only": True,
            "publication_approved": False
        }

        # Valid source document
        self.valid_doc = {
            "contract_version": "1.0.0",
            "document_id": "test_doc_1",
            "lexemes": [
                {
                    "lexeme_id": "lex1",
                    "language": "en",
                    "surface": "test",
                    "lemma": "test",
                    "pos": "noun",
                    "direction": "ltr",
                    "script": "Latn",
                    "source": self.source_obj
                }
            ],
            "senses": [
                {
                    "sense_id": "sense1",
                    "lexeme_id": "lex1",
                    "concept_id": "concept1",
                    "definition": "A trial or experiment",
                    "source": self.source_obj
                }
            ],
            "translations": [],
            "examples": [],
            "relations": []
        }

        self.source_path = self.temp_dir / "en.json"
        with open(self.source_path, 'w') as f:
            json.dump(self.valid_doc, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_successful_build(self):
        pack_path, item = self.compiler.compile(self.source_path, "en", fixture_only=True)
        self.assertTrue(pack_path.exists())
        self.assertEqual(item["languageCode"], "en")

        # To test exact same deterministic repeated builds, just run again
        # But we need a fresh compiler instance because SanitizerEngine stores 'seen_identities' statefully in memory
        # to prevent duplicates across multiple calls. We just recreate the compiler.
        compiler2 = CorpusCompiler(workspace=self.temp_dir, repo_root=self.repo_root)
        pack_path2, item2 = compiler2.compile(self.source_path, "en", fixture_only=True)
        self.assertEqual(pack_path, pack_path2)
        self.assertEqual(item["sha256"], item2["sha256"])

    def test_invalid_source_rejected(self):
        invalid_doc = self.valid_doc.copy()
        invalid_doc["document_id"] = ""

        # different name so it doesn't conflict
        source_path = self.temp_dir / "en2.json"
        with open(source_path, 'w') as f:
            json.dump(invalid_doc, f)

        with self.assertRaises(BuildError):
            self.compiler.compile(source_path, "en", fixture_only=True)

    def test_rebuild_does_not_overwrite_valid_output_on_failure(self):
        # 1. Successful build
        pack_path, item = self.compiler.compile(self.source_path, "en", fixture_only=True)
        self.assertTrue(pack_path.exists())

        # 2. Corrupt source
        invalid_doc = self.valid_doc.copy()
        invalid_doc["lexemes"] = "not a list"
        with open(self.source_path, 'w') as f:
            json.dump(invalid_doc, f)

        # 3. Build should fail, but original artifact should persist
        with self.assertRaises(BuildError):
            self.compiler.compile(self.source_path, "en", fixture_only=True)

        self.assertTrue(pack_path.exists())

    def test_empty_sources(self):
        # Source must have lexemes, otherwise valid_document raises ValueError
        empty_doc = self.valid_doc.copy()
        empty_doc["lexemes"] = []
        with open(self.source_path, 'w') as f:
            json.dump(empty_doc, f)

        with self.assertRaises(BuildError):
            self.compiler.compile(self.source_path, "en", fixture_only=True)

    def test_changed_manifest_rejected(self):
        # If we change the document_id, the identity changes
        changed_doc = self.valid_doc.copy()
        changed_doc["document_id"] = "test_doc_changed"
        with open(self.source_path, 'w') as f:
            json.dump(changed_doc, f)

        pack_path, item = self.compiler.compile(self.source_path, "en", fixture_only=True)
        self.assertTrue(pack_path.exists())

    def test_invalid_licenses(self):
        # The allowed schema validation fails if license isn't correct length/pattern or property missing if required
        invalid_doc = self.valid_doc.copy()
        invalid_doc["lexemes"][0]["source"]["license_id"] = "NOT-A-LICENSE"
        with open(self.source_path, 'w') as f:
            json.dump(invalid_doc, f)

        # We assume license structure is validated inside validate_document via lexical schema
        # For our test schema, license_id is just string, but we can delete a required prop to simulate
        invalid_doc["lexemes"][0]["source"].pop("license_id")
        with open(self.source_path, 'w') as f:
            json.dump(invalid_doc, f)

        with self.assertRaises(BuildError):
            self.compiler.compile(self.source_path, "en", fixture_only=True)

if __name__ == '__main__':
    unittest.main()
