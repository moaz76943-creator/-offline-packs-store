"""Review-only German Haus and Spanish villa from Wikidata Lexeme page facts."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-home-page-candidates"


class HomePageCandidatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = json.loads(cls.raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_sha256_canonical_and_counts(self):
        canonical = (json.dumps(self.data, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.assertEqual(self.raw, canonical)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),
                         self.receipt["candidate_sha256"])
        self.assertEqual(len(self.data["candidates"]), 2)
        self.assertEqual(len(self.data["lexemes"]), 2)
        self.assertEqual(sum(len(x["forms"]) for x in self.data["lexemes"]), 12)
        self.assertEqual((self.receipt["actual_rows"], self.receipt["form_count"]), (2, 12))

    def test_revision_provenance_and_forms(self):
        pages = {(x["language"], x["lexeme_id"]): x for x in self.receipt["source_pages"]}
        self.assertEqual(len(pages), 2)
        for lex in self.data["lexemes"]:
            key = (lex["language"], lex["lexeme_id"])
            self.assertIn(key, pages)
            url = (f"https://www.wikidata.org/w/index.php?title=Lexeme:"
                   f"{lex['lexeme_id']}&oldid={lex['revision']}")
            self.assertEqual(lex["page_url"], url)
            self.assertEqual(pages[key]["url"], url)
            self.assertEqual(lex["lexical_category"], "noun")
            ids = [form["id"] for form in lex["forms"]]
            self.assertEqual(len(ids), len(set(ids)))
            for form in lex["forms"]:
                self.assertRegex(form["id"], "^" + re.escape(lex["lexeme_id"]) +
                                 r"-F[1-9][0-9]*$")
                self.assertTrue(form["surface"])
                self.assertTrue(form["features"])
            self.assertIn(lex["lexeme_id"] + "-S2", lex["excluded_sense_ids"])
        self.assertEqual(self.data["lexemes"][0]["gender"], "neuter")
        self.assertEqual(self.data["lexemes"][0]["forms"][6]["surface"], "Häusern")
        self.assertEqual(self.data["lexemes"][1]["gender"], "feminine")
        self.assertEqual(self.data["lexemes"][1]["forms"][1]["surface"], "villas")

    def test_sense_specific_no_fabrication(self):
        expected = {"de:L2957:L2957-S1:concept.q3947",
                    "es:L659630:L659630-S1:concept.q3950"}
        self.assertEqual({r["id"] for r in self.data["candidates"]}, expected)
        for row in self.data["candidates"]:
            self.assertEqual(row["sense_id"], row["lexeme_id"] + "-S1")
            self.assertEqual((row["topic"], row["subtopic"], row["level"]),
                             ("home", "buildings", "UNKNOWN"))
            self.assertEqual((row["directed_translations"], row["examples"]), ([], []))
            self.assertIsNone(row["level_evidence"])
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")

    def test_license_and_production_gate(self):
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(),
                         self.receipt["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", notice)
        self.assertEqual(self.receipt["license_id"], "CC0-1.0")
        self.assertEqual(self.receipt["status"], "REVIEW_REQUIRED")
        for obj in (self.data, self.receipt):
            for field in ("original_source_bytes_pinned",
                          "source_admission_approved", "production_ready"):
                self.assertIs(obj[field], False)

    def test_cross_batch_no_duplicate_lexeme_sense(self):
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
