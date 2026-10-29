"""Wikidata L226769 Arabic mother: pinned review-only lexeme, forms and rights."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-ar-mother-page-batch5"
URL = "https://www.wikidata.org/w/index.php?title=Lexeme:L226769&oldid=2548821059"


class ArabicMotherPageBatch5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = json.loads(cls.raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_canonical_sha256_and_exact_counts(self):
        canonical = (json.dumps(self.data, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.assertEqual(self.raw, canonical)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), self.receipt["candidate_sha256"])
        self.assertEqual((len(self.data["candidates"]), len(self.data["lexemes"])), (1, 1))
        self.assertEqual((self.receipt["actual_rows"], self.receipt["form_count"],
                          self.receipt["variant_count"]), (1, 21, 7))

    def test_revision_pinned_attested_morphology(self):
        lex = self.data["lexemes"][0]
        self.assertEqual((lex["language"], lex["lexeme_id"], lex["lemma"]),
                         ("ar", "L226769", "أُمّ"))
        self.assertEqual((lex["gender"], lex["root"], lex["lexical_category"]),
                         ("feminine", "ء م م", "noun"))
        self.assertEqual((lex["revision"], lex["page_url"]), (2548821059, URL))
        self.assertEqual(self.receipt["source_pages"],
                         [{"language": "ar", "lexeme_id": "L226769",
                           "revision": 2548821059, "url": URL}])
        forms = lex["forms"]
        self.assertEqual([f["id"] for f in forms],
                         [f"L226769-F{i}" for i in range(1, 22)])
        self.assertEqual([f["surface"] for f in forms],
                         ["أُمٌّ", "أُمٍّ", "أُمًّا", "أُمَّهَٰتٌ", "أُمَّهَٰتٍ",
                          "أُمَّانِ", "أُمَّيْنِ", "أُمُّ", "أُمَّ", "أُمِّ",
                          "أُمَّا", "أُمَّيْ", "أُمَّهَٰتُ", "أُمَّهَٰتِ",
                          "الأُمُّ", "الأُمَّ", "الأُمِّ", "الأُمَّانِ",
                          "الأُمَّيْنِ", "الأُمَّهَٰتُ", "الأُمَّهَٰتِ"])
        self.assertEqual(sum(len(f.get("variants", [])) for f in forms), 7)
        for form in forms:
            self.assertIn("feminine", form["features"])
            self.assertTrue(form["surface"])
            for variant in form.get("variants", []):
                self.assertEqual(variant["language"], "ar-001")
                self.assertTrue(variant["surface"])

    def test_rights_and_review_only_gate(self):
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(),
                         self.receipt["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", notice)
        self.assertEqual(self.receipt["license_id"], "CC0-1.0")
        self.assertEqual(self.receipt["source_type"],
                         "MANUAL_PAGE_STRUCTURED_EXCERPT_NOT_ORIGINAL_JSON")
        self.assertEqual(self.receipt["status"], "REVIEW_REQUIRED")
        for obj in (self.data, self.receipt):
            for field in ("original_source_bytes_pinned",
                          "source_admission_approved", "production_ready"):
                self.assertIs(obj[field], False)
        row = self.data["candidates"][0]
        self.assertEqual(row["id"], "ar:L226769:L226769-S1:concept.q7560")
        self.assertEqual(row["source_snapshot"], URL)
        self.assertEqual((row["topic"], row["subtopic"], row["level"]),
                         ("family", "kinship", "UNKNOWN"))
        self.assertEqual((row["directed_translations"], row["examples"]), ([], []))
        self.assertIsNone(row["level_evidence"])
        self.assertEqual(row["review_status"], "REVIEW_REQUIRED")

    def test_no_cross_batch_sense_duplication(self):
        own = {(r["language"], r["lexeme_id"], r["sense_id"])
               for r in self.data["candidates"]}
        for path in (ROOT / "legal/ledger/evidence").glob("*/candidates.json"):
            if path.parent == FOLDER:
                continue
            other = json.loads(path.read_bytes())
            for row in other.get("candidates", []):
                self.assertNotIn((row["language"], row["lexeme_id"], row["sense_id"]),
                                 own, str(path))


if __name__ == "__main__":
    unittest.main()
