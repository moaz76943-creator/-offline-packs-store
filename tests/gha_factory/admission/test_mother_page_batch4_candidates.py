"""CC0 Wikidata mother page candidates: deterministic review-only admission tests."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-mother-page-batch4"

class MotherPageBatch4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = json.loads(cls.raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_exact_canonical_sha256_and_counts(self):
        canonical = (json.dumps(self.data, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.assertEqual(self.raw, canonical)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), self.receipt["candidate_sha256"])
        self.assertEqual((len(self.data["candidates"]), len(self.data["lexemes"])),
                         (2, 2))
        self.assertEqual(sum(len(x["forms"]) for x in self.data["lexemes"]), 10)
        self.assertEqual((self.receipt["actual_rows"], self.receipt["form_count"]), (2, 10))

    def test_immutable_source_identity_and_attested_forms(self):
        pages = {(p["language"], p["lexeme_id"]): p for p in self.receipt["source_pages"]}
        self.assertEqual(len(pages), 2)
        for lex in self.data["lexemes"]:
            key = (lex["language"], lex["lexeme_id"])
            self.assertIn(key, pages)
            url = (f"https://www.wikidata.org/w/index.php?title=Lexeme:"
                   f"{lex['lexeme_id']}&oldid={lex['revision']}")
            self.assertEqual(lex["page_url"], url)
            self.assertEqual(pages[key]["url"], url)
            self.assertEqual(lex["gender"], "feminine")
            self.assertEqual(lex["lexical_category"], "noun")
            ids = [form["id"] for form in lex["forms"]]
            self.assertEqual(len(ids), len(set(ids)))
            for form in lex["forms"]:
                self.assertRegex(form["id"], "^" + re.escape(lex["lexeme_id"]) + r"-F[1-9][0-9]*$")
                self.assertTrue(form["surface"])
                self.assertTrue(form["features"])
        de = next(x for x in self.data["lexemes"] if x["language"] == "de")
        fr = next(x for x in self.data["lexemes"] if x["language"] == "fr")
        self.assertEqual([x["surface"] for x in de["forms"]],
                         ["Mutter"] * 4 + ["Mütter", "Mütter", "Müttern", "Mütter"])
        self.assertEqual([x["surface"] for x in fr["forms"]], ["mères", "mère"])
        self.assertEqual(de["excluded_sense_ids"], ["L34041-S4", "L34041-S5"])

    def test_review_only_license_and_no_fabricated_translations(self):
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(),
                         self.receipt["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", notice)
        self.assertEqual(self.receipt["license_id"], "CC0-1.0")
        self.assertEqual(self.receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(self.receipt["source_type"],
                         "MANUAL_PAGE_STRUCTURED_EXCERPT_NOT_ORIGINAL_JSON")
        for obj in (self.data, self.receipt):
            for field in ("original_source_bytes_pinned",
                          "source_admission_approved", "production_ready"):
                self.assertIs(obj[field], False)
        for row in self.data["candidates"]:
            self.assertEqual(row["id"], ":".join((row["language"], row["lexeme_id"],
                                                  row["sense_id"], row["concept_id"])))
            self.assertEqual(row["concept_id"], "concept.q7560")
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
