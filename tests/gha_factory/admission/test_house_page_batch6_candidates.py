"""Review-only English/French house senses from Wikidata pinned Lexeme revisions."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-house-page-batch6"


class HousePageBatch6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = json.loads(cls.raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_exact_canonical_bytes_hash_and_counts(self):
        expected = (json.dumps(self.data, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        self.assertEqual(self.raw, expected)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], len(self.data["candidates"]))
        self.assertEqual(self.receipt["lexeme_count"], len(self.data["lexemes"]))
        self.assertEqual(self.receipt["form_count"],
                         sum(len(lex["forms"]) for lex in self.data["lexemes"]))
        self.assertEqual((self.receipt["actual_rows"], self.receipt["form_count"]), (2, 4))

    def test_exact_revision_pinned_source_lexemes(self):
        expected = {"en": ("L512", "house", 2549907679, None,
                           [("L512-F1", "house", ["singular"]),
                            ("L512-F2", "houses", ["plural"])]),
                    "fr": ("L525", "maison", 2520412252, "feminine",
                           [("L525-F1", "maisons", ["plural"]),
                            ("L525-F2", "maison", ["singular"])])}
        for lex in self.data["lexemes"]:
            lex_id, lemma, revision, gender, forms = expected[lex["language"]]
            self.assertEqual((lex["lexeme_id"], lex["lemma"], lex["revision"],
                              lex["gender"], lex["lexical_category"]),
                             (lex_id, lemma, revision, gender, "noun"))
            self.assertEqual(lex["page_url"],
                             f"https://www.wikidata.org/w/index.php?title=Lexeme:{lex_id}&oldid={revision}")
            self.assertEqual([(f["id"], f["surface"], f["features"]) for f in lex["forms"]],
                             forms)
            self.assertNotIn(f"{lex_id}-S1", lex["excluded_sense_ids"])
        self.assertEqual(set(expected), {x["language"] for x in self.data["lexemes"]})
        self.assertEqual({x["url"] for x in self.receipt["source_pages"]},
                         {x["page_url"] for x in self.data["lexemes"]})

    def test_attested_concept_and_no_false_directed_translations(self):
        lexemes = {x["lexeme_id"]: x for x in self.data["lexemes"]}
        self.assertEqual(len({x["id"] for x in self.data["candidates"]}), 2)
        for row in self.data["candidates"]:
            lex = lexemes[row["lexeme_id"]]
            self.assertEqual(row["id"],
                             f"{lex['language']}:{lex['lexeme_id']}:{lex['lexeme_id']}-S1:concept.q3947")
            self.assertEqual(row["concept_evidence"]["property"], "P5137")
            self.assertEqual(row["concept_evidence"]["item_id"], "Q3947")
            self.assertEqual(row["source_snapshot"], lex["page_url"])
            self.assertEqual((row["topic"], row["subtopic"], row["level"]),
                             ("home", "buildings", "UNKNOWN"))
            self.assertEqual((row["directed_translations"], row["examples"]), ([], []))
            self.assertIsNone(row["level_evidence"])
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")

    def test_scoped_license_and_fail_closed_review_status(self):
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(),
                         self.receipt["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", notice)
        self.assertEqual(self.receipt["license_id"], "CC0-1.0")
        self.assertEqual(self.receipt["source_type"],
                         "MANUAL_PAGE_STRUCTURED_EXCERPT_NOT_ORIGINAL_JSON")
        self.assertEqual(self.receipt["status"], "REVIEW_REQUIRED")
        for obj in (self.receipt, self.data):
            for field in ("original_source_bytes_pinned",
                          "source_admission_approved", "production_ready"):
                self.assertIs(obj[field], False)

    def test_cross_batch_lexeme_sense_dedup(self):
        own = {(row["language"], row["lexeme_id"], row["sense_id"])
               for row in self.data["candidates"]}
        for path in (ROOT / "legal/ledger/evidence").glob("*/candidates.json"):
            if path.parent == FOLDER:
                continue
            other = json.loads(path.read_bytes())
            for row in other.get("candidates", []):
                self.assertNotIn((row["language"], row["lexeme_id"], row["sense_id"]),
                                 own, str(path))


if __name__ == "__main__":
    unittest.main()
