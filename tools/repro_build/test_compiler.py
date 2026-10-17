import unittest
import tempfile
import os
import sqlite3
import copy
import json
from pathlib import Path
from tools.repro_build.compiler import ReproBuilder
from tools.lexicon_sanitizer.engine import SanitizerEngine

class TestReproBuilder(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.workspace = Path(self.td.name)
        self.repo_root = Path('tools/repro_build').absolute()

        source_dict = {
            "source_id": "src1",
            "origin_url": "https://example.com",
            "publisher": "Example Publisher",
            "dataset_version": "1.0",
            "license_id": "CC0-1.0",
            "retrieval_id": "rt1",
            "artifact_sha256": "0" * 64,
            "fixture_only": True,
            "publication_approved": False
        }

        self.valid_doc = {
            "document_id": "test_doc",
            "contract_version": "1.0.0",
            "lexemes": [
                {
                    "lexeme_id": "lex1",
                    "language": "eng",
                    "lemma": "test",
                    "surface": "test",
                    "pos": "noun",
                    "direction": "ltr",
                    "script": "Latn",
                    "source": source_dict
                }
            ],
            "senses": [
                {
                    "sense_id": "sen1",
                    "lexeme_id": "lex1",
                    "concept_id": "con1",
                    "definition": "A test definition",
                    "source": source_dict
                }
            ],
            "translations": [],
            "examples": [],
            "relations": []
        }

        self.registry_path = self.workspace / 'language_registry.v1.json'
        with open(self.registry_path, 'w') as f:
            f.write('{"languages": {"eng": {}}}')

        self.engine = SanitizerEngine(registry_path=str(self.registry_path))

        # Prepare a mock ledger for testing invalid licenses (fixture_only=False)
        self.ledger_dir = self.repo_root / 'legal' / 'ledger'
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.ledger_dir / 'sources.json'

    def tearDown(self):
        self.td.cleanup()

    def _get_builder(self):
        return ReproBuilder(engine=SanitizerEngine(registry_path=str(self.registry_path)))

    def test_basic_compile(self):
        path, counts = self._get_builder().compile(
            self.valid_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=True
        )
        self.assertTrue(path.exists())
        self.assertTrue(path.name.endswith('.sqlite'))
        self.assertIn('eng_', path.name)
        self.assertEqual(counts['lexicon'], 1)

    def test_empty_sources(self):
        empty_doc = copy.deepcopy(self.valid_doc)
        empty_doc['lexemes'] = []
        with self.assertRaises(ValueError):
            self._get_builder().compile(empty_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=True)

    def test_malformed_records(self):
        malformed = copy.deepcopy(self.valid_doc)
        malformed['lexemes'] = "not a list"
        with self.assertRaises(ValueError):
            self._get_builder().compile(malformed, 'eng', [], self.workspace, self.repo_root, fixture_only=True)

    def test_preserve_previous_valid_artifact_on_failure(self):
        path, counts = self._get_builder().compile(
            self.valid_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=True
        )
        final_output = self.workspace / path.name
        self.assertTrue(final_output.exists())

        with open(final_output, 'rb') as f:
            original_content = f.read()

        invalid_doc = copy.deepcopy(self.valid_doc)
        invalid_doc['lexemes'] = []
        with self.assertRaises(ValueError):
            self._get_builder().compile(invalid_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=True)

        self.assertTrue(final_output.exists())
        with open(final_output, 'rb') as f:
            self.assertEqual(f.read(), original_content)

    def test_deterministic_repeated_builds(self):
        path1, _ = self._get_builder().compile(
            self.valid_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=True
        )
        with open(path1, 'rb') as f:
            hash1 = f.read()

        path2, _ = self._get_builder().compile(
            self.valid_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=True
        )
        with open(path2, 'rb') as f:
            hash2 = f.read()

        self.assertEqual(hash1, hash2)
        self.assertEqual(path1.name, path2.name)

    def test_invalid_licenses(self):
        invalid_doc = copy.deepcopy(self.valid_doc)
        invalid_doc['lexemes'][0]['source']['fixture_only'] = False
        invalid_doc['lexemes'][0]['source']['publication_approved'] = True
        invalid_doc['lexemes'][0]['source']['license_id'] = "UNKNOWN-LICENSE"
        invalid_doc['senses'][0]['source']['fixture_only'] = False
        invalid_doc['senses'][0]['source']['publication_approved'] = True
        invalid_doc['senses'][0]['source']['license_id'] = "UNKNOWN-LICENSE"

        mock_ledger = {
            "schema_version": "1.0.0",
            "sources": [
                {
                    "source_id": "src1",
                    "origin_url": "https://example.com",
                    "publisher": "Example Publisher",
                    "dataset_version": "1.0",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "review": {
                        "decision_url": "https://example.com/review",
                        "reviewer": "test"
                    },
                    "retrieval": {
                        "identity": "rt1",
                        "sha256": "0"*64,
                        "artifact_path": "a.txt"
                    },
                    "license": {
                        "id": "UNKNOWN-LICENSE",
                        "evidence_url": "https://example.com",
                        "evidence_path": "a.txt",
                        "evidence_sha256": "0"*64
                    },
                    "alterations": ["none"]
                }
            ]
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(mock_ledger, f)

        # create mock artifacts to bypass _verified_artifact
        (self.repo_root / "a.txt").write_bytes(b"")

        with self.assertRaises(ValueError) as ctx:
            self._get_builder().compile(invalid_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=False)
        self.assertIn('unsupported license', str(ctx.exception))

    def test_changed_manifests(self):
        path1, _ = self._get_builder().compile(
            self.valid_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=True
        )

        changed_doc = copy.deepcopy(self.valid_doc)
        changed_doc['senses'][0]['definition'] = "A modified definition"

        path2, _ = self._get_builder().compile(
            changed_doc, 'eng', [], self.workspace, self.repo_root, fixture_only=True
        )

        self.assertNotEqual(path1.name, path2.name)

if __name__ == '__main__':
    unittest.main()
