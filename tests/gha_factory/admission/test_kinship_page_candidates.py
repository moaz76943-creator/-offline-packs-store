"""Verify CC0 Wikidata page-derived kinship candidates (review-only)."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261025-kinship-page-candidates"

class KinshipPageCandidatesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = json.loads(cls.raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_hash_and_count(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), self.receipt["candidate_sha256"])
        self.assertEqual(self.raw, (json.dumps(self.data, sort_keys=True, ensure_ascii=False,
                                              separators=(",", ":")) + "\n").encode())
        self.assertEqual((len(self.data["candidates"]), len(self.data["lexemes"]),
                          sum(len(x["forms"]) for x in self.data["lexemes"])), (4, 3, 12))
        self.assertEqual((self.receipt["actual_rows"], self.receipt["lexeme_count"],
                          self.receipt["form_count"]), (4, 3, 12))

    def test_license_and_unapproved_source(self):
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(), self.receipt["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", notice)
        self.assertEqual(self.receipt["license_id"], "CC0-1.0")
        for field in ("original_source_bytes_pinned", "source_admission_approved", "production_ready"):
            self.assertIs(self.data[field], False)
            self.assertIs(self.receipt[field], False)

    def test_revision_and_forms(self):
        for lex in self.data["lexemes"]:
            self.assertRegex(lex["lexeme_id"], r"^L[1-9][0-9]*$")
            self.assertEqual(lex["page_url"],
                             f"https://www.wikidata.org/w/index.php?title=Lexeme:{lex['lexeme_id']}&oldid={lex['revision']}")
            ids = [x["id"] for x in lex["forms"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(re.fullmatch(re.escape(lex["lexeme_id"]) + r"-F[1-9][0-9]*", x) for x in ids))
        de = next(x for x in self.data["lexemes"] if x["language"] == "de")
        self.assertEqual(de["gender"], "feminine")
        self.assertEqual(next(x["surface"] for x in de["forms"] if x["id"] == "L400216-F7"), "Töchtern")
        self.assertTrue(all(x["gender"] is None for x in self.data["lexemes"] if x["language"] == "en"))

    def test_identity_and_review_only(self):
        rows = self.data["candidates"]
        self.assertEqual(len({x["id"] for x in rows}), len(rows))
        lex = {(x["language"], x["lexeme_id"]) for x in self.data["lexemes"]}
        for x in rows:
            self.assertIn((x["language"], x["lexeme_id"]), lex)
            self.assertEqual(x["id"], ":".join((x["language"], x["lexeme_id"], x["sense_id"], x["concept_id"])))
            self.assertRegex(x["concept_id"], r"^concept\\.q[1-9][0-9]*$")
            self.assertEqual((x["topic"], x["subtopic"], x["level"]), ("family", "kinship", "UNKNOWN"))
            self.assertEqual((x["directed_translations"], x["examples"], x["review_status"]),
                             ([], [], "REVIEW_REQUIRED"))

if __name__ == "__main__":
    unittest.main()
