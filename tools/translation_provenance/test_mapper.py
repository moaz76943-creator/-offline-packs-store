import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from tools.contribution_gate.test_fixture import fixture, ref, put, save_ledger
from tools.translation_provenance.mapper import map_provenance

class MapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger, self.source = fixture(self.root)
        self.translation_sha = put(self.root, "evidence/translation.txt", b"attested pair")
        self.records = [
            {"type": "sense", "sense_id": "sense-en", "lexeme_id": "lex-en",
             "language": "en", "source_locator": "row 1", "source": ref(self.source)},
            {"type": "sense", "sense_id": "sense-de", "lexeme_id": "lex-de",
             "language": "de", "source_locator": "row 2", "source": ref(self.source)},
            {"type": "translation", "translation_id": "edge-1",
             "from_sense_id": "sense-en", "to_sense_id": "sense-de",
             "from_language": "en", "to_language": "de", "source": ref(self.source),
             "translation_evidence": {"source_locator": "row 3",
                                      "artifact_path": "evidence/translation.txt",
                                      "sha256": self.translation_sha}}
        ]
    def run_gate(self, records=None):
        lines = "\n".join(json.dumps(r) for r in (records if records is not None else self.records))
        return list(map_provenance(StringIO(lines), self.ledger, repo_root=self.root))
    def test_injected_approved_manifest_cannot_override_canonical_empty_ledger(self):
        save_ledger(self.root, {"schema_version": "1.0.0", "sources": []})
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.run_gate()

    def test_exact_direction_and_source_identity(self):
        data = self.run_gate()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["from_sense_id"], "sense-en")
        self.assertEqual(data[0]["to_language"], "de")
        self.assertTrue(data[0]["evidence_only"])
    def test_missing_all_senses_is_orphan_not_success(self):
        with self.assertRaises(ValueError):
            self.run_gate([self.records[-1]])
    def test_missing_target_sense(self):
        with self.assertRaisesRegex(ValueError, "Orphan"):
            self.run_gate([self.records[0], self.records[-1]])
    def test_forged_source_hash(self):
        self.records[-1]["source"]["artifact_sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            self.run_gate()
    def test_missing_translation_evidence(self):
        del self.records[-1]["translation_evidence"]
        with self.assertRaises(ValueError):
            self.run_gate()
    def test_changed_translation_bytes(self):
        (self.root / "evidence/translation.txt").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.run_gate()
    def test_direction_must_match_senses(self):
        self.records[-1]["from_language"] = "de"
        with self.assertRaises(ValueError):
            self.run_gate()
    def test_revoked_rights(self):
        self.source["status"] = "REVIEW_REQUIRED"
        with self.assertRaises(ValueError):
            self.run_gate()
    def test_duplicate_translation_id(self):
        with self.assertRaises(ValueError):
            self.run_gate(self.records + [self.records[-1]])
    def test_missing_sense_lexeme_id(self):
        del self.records[0]["lexeme_id"]
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_source_mismatch(self):
        self.records[-1]["source"]["dataset_version"] = "v2"
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_invalid_language_direction(self):
        self.records[0]["language"] = "de"
        self.records[-1]["from_language"] = "de"
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_multiple_senses(self):
        self.records.extend([
            {"type": "sense", "sense_id": "sense-en-2", "lexeme_id": "lex-en",
             "language": "en", "source_locator": "row 4", "source": ref(self.source)},
            {"type": "sense", "sense_id": "sense-de-2", "lexeme_id": "lex-de",
             "language": "de", "source_locator": "row 5", "source": ref(self.source)},
            {"type": "translation", "translation_id": "edge-2",
             "from_sense_id": "sense-en-2", "to_sense_id": "sense-de-2",
             "from_language": "en", "to_language": "de", "source": ref(self.source),
             "translation_evidence": {"source_locator": "row 6",
                                      "artifact_path": "evidence/translation.txt",
                                      "sha256": self.translation_sha}}
        ])
        data = self.run_gate()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["translation_id"], "edge-1")
        self.assertEqual(data[1]["translation_id"], "edge-2")

    def test_conflicting_translations(self):
        self.records.append(
            {"type": "translation", "translation_id": "edge-duplicate",
             "from_sense_id": "sense-en", "to_sense_id": "sense-de",
             "from_language": "en", "to_language": "de", "source": ref(self.source),
             "translation_evidence": {"source_locator": "row 7",
                                      "artifact_path": "evidence/translation.txt",
                                      "sha256": self.translation_sha}}
        )
        with self.assertRaisesRegex(ValueError, "Conflicting translation"):
            self.run_gate()

    def test_altered_hashes(self):
        self.records[-1]["translation_evidence"]["sha256"] = "c" * 64
        with self.assertRaises(ValueError):
            self.run_gate()

if __name__ == "__main__":
    unittest.main()
