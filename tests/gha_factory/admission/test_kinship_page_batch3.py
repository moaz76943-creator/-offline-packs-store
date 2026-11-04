"""Review-only Wikidata Lexeme page facts: brother, grand-aunt, moster."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-kinship-page-batch3"

def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)

class KinshipPageBatch3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = strict_json(cls.raw)
        cls.receipt = strict_json((FOLDER / "receipt.json").read_bytes())

    def test_canonical_sha256_and_actual_counts(self):
        expected = (json.dumps(self.data, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.assertEqual(self.raw, expected)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), self.receipt["candidate_sha256"])
        self.assertEqual((self.receipt["actual_rows"], self.receipt["lexeme_count"],
                          self.receipt["form_count"]), (3, 3, 8))
        self.assertEqual(len(self.data["candidates"]), 3)
        self.assertEqual(sum(len(x["forms"]) for x in self.data["lexemes"]), 8)

    def test_pinned_lexeme_identity_forms_and_variant(self):
        pages = {(x["language"], x["lexeme_id"]): x for x in self.receipt["source_pages"]}
        self.assertEqual(len(pages), 3)
        for lex in self.data["lexemes"]:
            key = (lex["language"], lex["lexeme_id"])
            self.assertIn(key, pages)
            url = f"https://www.wikidata.org/w/index.php?title=Lexeme:{lex['lexeme_id']}&oldid={lex['revision']}"
            self.assertEqual(lex["page_url"], url)
            self.assertEqual(pages[key]["url"], url)
            ids = [f["id"] for f in lex["forms"]]
            self.assertEqual(len(ids), len(set(ids)))
            for f in lex["forms"]:
                self.assertRegex(f["id"], "^" + re.escape(lex["lexeme_id"]) + r"-F[1-9][0-9]*$")
                self.assertTrue(f["surface"])
        brother = next(x for x in self.data["lexemes"] if x["lexeme_id"] == "L3627")
        grandaunt = next(x for x in self.data["lexemes"] if x["lexeme_id"] == "L321384")
        moster = next(x for x in self.data["lexemes"] if x["lexeme_id"] == "L482456")
        self.assertIsNone(brother["gender"])
        self.assertEqual(grandaunt["forms"][0]["alternate_surface"], "grandaunt")
        self.assertEqual(grandaunt["forms"][0]["alternate_variant"], "en-us")
        self.assertEqual(moster["gender"], "common")
        self.assertEqual(moster["forms"][3]["surface"], "mostrarna")

    def test_review_only_no_fabricated_cefr_or_translations(self):
        for item in (self.data, self.receipt):
            self.assertIs(item["production_ready"], False)
            self.assertIs(item["source_admission_approved"], False)
            self.assertIs(item["original_source_bytes_pinned"], False)
        self.assertEqual(self.receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(self.receipt["license_id"], "CC0-1.0")
        self.assertEqual(self.receipt["directed_translations"], 0)
        self.assertEqual(self.receipt["examples"], 0)
        expected = {
            "en:L3627:L3627-S1:concept.q10861465",
            "en:L321384:L321384-S1:concept.q11972456",
            "sv:L482456:L482456-S1:concept.q6035384",
        }
        self.assertEqual({r["id"] for r in self.data["candidates"]}, expected)
        for row in self.data["candidates"]:
            self.assertEqual((row["topic"], row["subtopic"], row["level"]),
                             ("family", "kinship", "UNKNOWN"))
            self.assertEqual((row["examples"], row["directed_translations"]), ([], []))
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertIsNone(row["level_evidence"])

    def test_license_notice_hash_and_scope(self):
        p = ROOT / self.receipt["license_evidence_path"]
        raw = p.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         self.receipt["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", raw)
        self.assertIn(b"CC0-1.0", raw)

    def test_no_duplicate_senses_in_prior_review_batches(self):
        own = {(x["language"], x["lexeme_id"], x["sense_id"])
               for x in self.data["candidates"]}
        for path in (ROOT / "legal/ledger/evidence").glob("*/candidates.json"):
            if path.parent == FOLDER:
                continue
            other = strict_json(path.read_bytes())
            for row in other.get("candidates", []):
                self.assertNotIn((row["language"], row["lexeme_id"], row["sense_id"]),
                                 own, str(path))

    def test_strict_json_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            strict_json(b'{"source":1,"source":2}')

if __name__ == "__main__":
    unittest.main()
