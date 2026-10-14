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

    def test_multiple_senses_polysemy(self):
        new_records = list(self.records)
        new_records.extend([
            {"type": "sense", "sense_id": "sense-en-2", "lexeme_id": "lex-en",
             "language": "en", "source_locator": "row 1a", "source": ref(self.source)},
            {"type": "translation", "translation_id": "edge-2",
             "from_sense_id": "sense-en-2", "to_sense_id": "sense-de",
             "from_language": "en", "to_language": "de", "source": ref(self.source),
             "translation_evidence": {"source_locator": "row 3a",
                                      "artifact_path": "evidence/translation.txt",
                                      "sha256": self.translation_sha}}
        ])
        data = self.run_gate(new_records)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["from_sense_id"], "sense-en")
        self.assertEqual(data[1]["from_sense_id"], "sense-en-2")

    def test_reverse_direction_is_separate(self):
        new_records = list(self.records)
        new_records.append(
            {"type": "translation", "translation_id": "edge-2",
             "from_sense_id": "sense-de", "to_sense_id": "sense-en",
             "from_language": "de", "to_language": "en", "source": ref(self.source),
             "translation_evidence": {"source_locator": "row 4",
                                      "artifact_path": "evidence/translation.txt",
                                      "sha256": self.translation_sha}}
        )
        data = self.run_gate(new_records)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["from_language"], "en")
        self.assertEqual(data[0]["to_language"], "de")
        self.assertEqual(data[1]["from_language"], "de")
        self.assertEqual(data[1]["to_language"], "en")

    def test_same_language_translation_fails(self):
        new_records = list(self.records)
        new_records.append(
            {"type": "sense", "sense_id": "sense-en-3", "lexeme_id": "lex-en-3",
             "language": "en", "source_locator": "row 5", "source": ref(self.source)}
        )
        new_records.append(
            {"type": "translation", "translation_id": "edge-3",
             "from_sense_id": "sense-en", "to_sense_id": "sense-en-3",
             "from_language": "en", "to_language": "en", "source": ref(self.source),
             "translation_evidence": {"source_locator": "row 6",
                                      "artifact_path": "evidence/translation.txt",
                                      "sha256": self.translation_sha}}
        )
        with self.assertRaisesRegex(ValueError, "Invalid language direction"):
            self.run_gate(new_records)

    def test_regional_variant_and_contextual_label(self):
        new_records = list(self.records)
        new_records[-1]["regional_variant"] = "GB"
        new_records[-1]["contextual_label"] = "informal"
        data = self.run_gate(new_records)
        self.assertEqual(data[0]["regional_variant"], "GB")
        self.assertEqual(data[0]["contextual_label"], "informal")

    def test_stale_dataset_version(self):
        self.records[-1]["source"]["dataset_version"] = "v2"
        with self.assertRaisesRegex(ValueError, "Missing or stale dataset_version"):
            self.run_gate()

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

if __name__ == "__main__":
    unittest.main()
