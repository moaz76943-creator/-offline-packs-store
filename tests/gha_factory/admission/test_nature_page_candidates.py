"""Review-only dog sense candidates from revision-pinned Wikidata Lexeme pages.

Original EntityData JSON is not retained: no source admission or production approval.
"""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-nature-page-candidates"


class NaturePageCandidatesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = json.loads(cls.raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_canonical_sha256_and_actual_counts(self):
        expected = (json.dumps(self.data, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")) + "\n").encode("utf-8")
        self.assertEqual(self.raw, expected)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), self.receipt["candidate_sha256"])
        self.assertEqual(len(self.data["candidates"]), self.receipt["actual_rows"])
        self.assertEqual(len(self.data["lexemes"]), self.receipt["lexeme_count"])
        self.assertEqual(sum(len(x["forms"]) for x in self.data["lexemes"]),
                         self.receipt["form_count"])
        self.assertEqual((self.receipt["actual_rows"], self.receipt["form_count"]), (4, 22))

    def test_license_evidence_and_review_only(self):
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(),
                         self.receipt["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", notice)
        self.assertEqual(self.receipt["license_id"], "CC0-1.0")
        for field in ("original_source_bytes_pinned", "source_admission_approved",
                      "production_ready"):
            self.assertIs(self.receipt[field], False)
            self.assertIs(self.data[field], False)
        self.assertEqual(self.receipt["status"], "REVIEW_REQUIRED")

    def test_revision_pinned_forms_and_lexeme_identity(self):
        self.assertEqual({x["language"] for x in self.data["lexemes"]},
                         {"de", "en", "es", "fr"})
        self.assertEqual(len({x["lexeme_id"] for x in self.data["lexemes"]}), 4)
        for lex in self.data["lexemes"]:
            lexeme_id = lex["lexeme_id"]
            self.assertRegex(lexeme_id, r"^L[1-9][0-9]*$")
            self.assertEqual(lex["page_url"],
                             f"https://www.wikidata.org/w/index.php?title=Lexeme:{lexeme_id}&oldid={lex['revision']}")
            self.assertEqual(lex["lexical_category"], "noun")
            ids = [f["id"] for f in lex["forms"]]
            self.assertEqual(len(ids), len(set(ids)))
            for form in lex["forms"]:
                self.assertTrue(re.fullmatch(re.escape(lexeme_id) + r"-F[1-9][0-9]*",
                                             form["id"]))
                self.assertTrue(form["surface"])
                self.assertTrue(form["features"])
            self.assertNotIn(f"{lexeme_id}-S1", lex["excluded_sense_ids"])

    def test_sense_specific_q144_no_unsupported_translations_or_cefr(self):
        lexemes = {(x["language"], x["lexeme_id"]): x for x in self.data["lexemes"]}
        rows = self.data["candidates"]
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        for row in rows:
            lex = lexemes[(row["language"], row["lexeme_id"])]
            self.assertEqual(row["sense_id"], row["lexeme_id"] + "-S1")
            self.assertEqual(row["id"], ":".join((row["language"], row["lexeme_id"],
                                                  row["sense_id"], "concept.q144")))
            self.assertEqual(row["concept_id"], "concept.q144")
            self.assertEqual(row["source_snapshot"], lex["page_url"])
            self.assertEqual((row["topic"], row["subtopic"], row["level"]),
                             ("nature", "animals", "UNKNOWN"))
            self.assertEqual((row["directed_translations"], row["examples"],
                              row["review_status"]), ([], [], "REVIEW_REQUIRED"))
        self.assertIsNone(lexemes[("en", "L1122")]["gender"])
        self.assertEqual(lexemes[("es", "L34109")]["gender_variants"],
                         ["masculine", "feminine"])
        self.assertEqual(lexemes[("de", "L34727")]["gender"], "masculine")
        self.assertEqual(lexemes[("fr", "L241")]["gender"], "masculine")

    def test_cross_batch_identity_dedup(self):
        current = {r["id"] for r in self.data["candidates"]}
        for file in (ROOT / "legal/ledger/evidence").glob("*/candidates.json"):
            if file.parent == FOLDER:
                continue
            prior = json.loads(file.read_text(encoding="utf-8"))
            self.assertFalse(current.intersection(r["id"] for r in prior["candidates"]),
                             f"duplicate candidate in {file}")


if __name__ == "__main__":
    unittest.main()
