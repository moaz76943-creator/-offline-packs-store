import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tools.contribution_gate.test_fixture import fixture, ref, put, save_ledger
from tools.translation_provenance.mapper import main, map_provenance

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

    def test_invalid_language_direction(self):
        self.records[0]["language"] = "de"
        self.records[1]["language"] = "de"
        self.records[-1]["from_language"] = "de"
        with self.assertRaisesRegex(ValueError, "Invalid language direction"):
            self.run_gate()

    def test_conflicting_translations(self):
        self.records.append(self.records[-1].copy())
        # The conflicting translation has a duplicate ID
        with self.assertRaisesRegex(ValueError, "Duplicate translation_id"):
            self.run_gate()

        self.records.pop()

        # Test translation with contradictory direction
        self.records[-1]["from_language"] = "fr"
        with self.assertRaisesRegex(ValueError, "Translation direction contradicts sense ownership"):
            self.run_gate()

    def test_altered_hashes(self):
        self.records[-1]["translation_evidence"]["sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH|hash"):
            self.run_gate()

    def test_preserve_regional_variants_and_contextual_labels(self):
        self.records[-1]["regional_variant"] = "Swiss German"
        self.records[-1]["contextual_label"] = "finance"
        data = self.run_gate()
        self.assertEqual(data[0]["regional_variant"], "Swiss German")
        self.assertEqual(data[0]["contextual_label"], "finance")

    def test_multiple_senses_preserved(self):
        # Adding another sense and translation to ensure multiple distinct meanings are preserved
        self.records.extend([
            {"type": "sense", "sense_id": "sense-en-2", "lexeme_id": "lex-en-2",
             "language": "en", "source_locator": "row 4", "source": ref(self.source)},
            {"type": "sense", "sense_id": "sense-fr", "lexeme_id": "lex-fr",
             "language": "fr", "source_locator": "row 5", "source": ref(self.source)},
            {"type": "translation", "translation_id": "edge-2",
             "from_sense_id": "sense-en-2", "to_sense_id": "sense-fr",
             "from_language": "en", "to_language": "fr", "source": ref(self.source),
             "translation_evidence": {"source_locator": "row 6",
                                      "artifact_path": "evidence/translation.txt",
                                      "sha256": self.translation_sha}}
        ])
        data = self.run_gate()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["translation_id"], "edge-1")
        self.assertEqual(data[1]["translation_id"], "edge-2")
        self.assertEqual(data[1]["from_sense_id"], "sense-en-2")
        self.assertEqual(data[1]["to_sense_id"], "sense-fr")

    def test_source_mismatch_dataset_version(self):
        self.records[-1]["source"]["dataset_version"] = "9.9.9"
        with self.assertRaises(ValueError):
            self.run_gate()

    def _invoke(self, lines):
        path = self.root / "translations.jsonl"
        path.write_text(lines, encoding="utf-8")
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([
                "--sources", str(self.root / "legal/ledger/sources.json"),
                "--translations", str(path),
                "--repo-root", str(self.root),
            ])
        return code, out.getvalue(), err.getvalue()

    def test_file_input_is_read_while_open(self):
        lines = "\n".join(json.dumps(r) for r in self.records) + "\n"
        code, out, err = self._invoke(lines)
        self.assertEqual(code, 0, err)
        self.assertIn("edge-1", out)
        self.assertNotIn("closed file", err)

    def test_valid_record_is_not_emitted_before_stream_eof(self):
        lines = "\n".join(json.dumps(r) for r in self.records) + "\n{not-json\n"
        out = StringIO()
        with self.assertRaises(ValueError):
            for record in map_provenance(StringIO(lines), self.ledger, repo_root=self.root):
                print(json.dumps(record), file=out)
        self.assertEqual(out.getvalue(), "")

    def test_malformed_tail_writes_no_stdout(self):
        lines = "\n".join(json.dumps(r) for r in self.records) + "\n{not-json\n"
        code, out, err = self._invoke(lines)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("BLOCKED:", err)

    def test_duplicate_after_valid_record_writes_no_stdout(self):
        lines = "\n".join(json.dumps(r) for r in self.records + [self.records[-1]]) + "\n"
        code, out, err = self._invoke(lines)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("BLOCKED:", err)

if __name__ == "__main__":
    unittest.main()
