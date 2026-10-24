"""Regression tests for genuine revision-pinned, UNAPPROVED lexical candidates."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.gha_factory.admission.review_only_wikidata import (
    DEFAULT_CANDIDATE, DEFAULT_DOSSIER, ReviewError, build, checked,
)

ROOT = Path(__file__).resolve().parents[3]


class WikidataReviewCandidatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated = build(ROOT, DEFAULT_DOSSIER)
        cls.committed = json.loads((ROOT / DEFAULT_CANDIDATE).read_text(encoding="utf-8"))

    def test_pinned_originals_reproduce_committed_candidate_inventory(self):
        self.assertEqual(self.generated, self.committed)

    def test_attested_three_languages_and_exact_counts(self):
        self.assertEqual(self.generated["summary"], {
            "lexemes": 3, "senses": 25, "forms": 40, "languages": ["ar", "de", "en"],
        })
        by_lang = {row["language"]: row for row in self.generated["lexemes"]}
        self.assertEqual({key: row["lemma"] for key, row in by_lang.items()},
                         {"de": "gehen", "en": "go", "ar": "ذَهَبَ"})
        self.assertEqual({key: len(row["forms"]) for key, row in by_lang.items()},
                         {"de": 32, "en": 5, "ar": 3})
        self.assertEqual({key: len(row["senses"]) for key, row in by_lang.items()},
                         {"de": 5, "en": 19, "ar": 1})

    def test_no_unreviewed_publication_or_inferred_levels(self):
        self.assertEqual(self.generated["status"], "REVIEW_REQUIRED")
        self.assertIs(self.generated["publication_approved"], False)
        for row in self.generated["lexemes"]:
            with self.subTest(row=row["entity_id"]):
                self.assertEqual(row["source_status"], "REVIEW_REQUIRED")
                self.assertEqual(row["license_id"], "CC0-1.0")
                self.assertEqual(row["level_status"], "UNKNOWN")
                self.assertEqual(row["topic_status"], "UNASSIGNED")
                self.assertEqual(row["directed_translations"], [])
                self.assertEqual(row["examples"], [])
                self.assertIs(row["publication_approved"], False)
                self.assertNotIn("cefr", row)
                self.assertNotIn("translations", row)
                self.assertTrue(all(form["form_id"].startswith(row["entity_id"] + "-F")
                                    for form in row["forms"]))
                self.assertTrue(all(sense["sense_id"].startswith(row["entity_id"] + "-S")
                                    for sense in row["senses"]))

    def test_tampered_candidate_is_not_equal_to_pinned_evidence(self):
        altered = copy.deepcopy(self.committed)
        altered["lexemes"][0]["forms"][0]["surface"] = "fabricated"
        self.assertNotEqual(altered, build(ROOT, DEFAULT_DOSSIER))
        altered = copy.deepcopy(self.committed)
        altered["publication_approved"] = True
        self.assertNotEqual(altered, build(ROOT, DEFAULT_DOSSIER))

    def test_original_source_hash_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.json"
            original = b'{"source":"verified"}\n'
            path.write_bytes(original)
            digest = hashlib.sha256(original).hexdigest()
            self.assertEqual(checked(folder, "source.json", digest), original)
            path.write_bytes(b'{"source":"tampered"}\n')
            with self.assertRaisesRegex(ReviewError, "SHA256 mismatch"):
                checked(folder, "source.json", digest)

    def test_symlink_and_parent_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "original"
            original.write_bytes(b"original")
            (root / "link").symlink_to(original)
            digest = hashlib.sha256(b"original").hexdigest()
            with self.assertRaisesRegex(ReviewError, "symlink"):
                checked(root, "link", digest)
            with self.assertRaisesRegex(ReviewError, "unsafe"):
                checked(root, "../original", digest)

    def test_duplicate_source_json_keys_rejected(self):
        from tools.gha_factory.admission.review_only_wikidata import _decode
        with self.assertRaisesRegex(ReviewError, "duplicate JSON key"):
            _decode(b'{"entities":{},"entities":{}}')


if __name__ == "__main__":
    unittest.main()
