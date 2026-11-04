"""Wikidata CC0 kinship page excerpts: REVIEW_REQUIRED only, offline QA."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261025-kinship-page-batch2"


class KinshipPageBatch2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = json.loads(cls.raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_sha_counts_and_licensing(self):
        r, d = self.receipt, self.data
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), r["candidate_sha256"])
        self.assertEqual(self.raw, (json.dumps(d, ensure_ascii=False, sort_keys=True,
                                              separators=(",", ":")) + "\n").encode())
        self.assertEqual((r["actual_rows"], r["lexeme_count"], r["form_count"]),
                         (len(d["candidates"]), len(d["lexemes"]),
                          sum(len(x["forms"]) for x in d["lexemes"])))
        self.assertEqual((r["actual_rows"], r["lexeme_count"], r["form_count"]), (5, 5, 39))
        notice = (ROOT / r["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(), r["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", notice)
        self.assertEqual((r["license_id"], r["status"]), ("CC0-1.0", "REVIEW_REQUIRED"))
        for flag in ("original_source_bytes_pinned", "source_admission_approved", "production_ready"):
            self.assertIs(r[flag], False)
            self.assertIs(d[flag], False)

    def test_revision_pins_and_attested_forms(self):
        expected = {
            "L238394": ("ar", "أَب", 2548339240, 19),
            "L34042": ("de", "Vater", 2544525397, 8),
            "L612368": ("de", "Stiefvater", 2336685167, 8),
            "L3624": ("en", "father", 2549873785, 2),
            "L2245": ("fr", "père", 2525514161, 2),
        }
        self.assertEqual(set(expected), {x["lexeme_id"] for x in self.data["lexemes"]})
        for lex in self.data["lexemes"]:
            lid = lex["lexeme_id"]
            lang, lemma, rev, count = expected[lid]
            self.assertEqual((lex["language"], lex["lemma"], lex["revision"],
                              len(lex["forms"])), (lang, lemma, rev, count))
            self.assertEqual(lex["page_url"],
                             f"https://www.wikidata.org/w/index.php?title=Lexeme:{lid}&oldid={rev}")
            self.assertEqual([f["id"] for f in lex["forms"]],
                             [f"{lid}-F{i}" for i in range(1, count + 1)])
            self.assertTrue(all(f["surface"] and f["features"] for f in lex["forms"]))
        ar = next(x for x in self.data["lexemes"] if x["language"] == "ar")
        self.assertEqual((ar["root_pattern"], ar["gender"]), ("ء ب و", "masculine"))
        self.assertEqual(ar["forms"][7]["vocalized_surface"], "أَبَوَانِ")
        self.assertIn("dual", ar["forms"][7]["features"])
        self.assertIsNone(next(x for x in self.data["lexemes"]
                               if x["language"] == "en")["gender"])

    def test_sense_identity_and_no_fabricated_content(self):
        rows = self.data["candidates"]
        self.assertEqual(len({r["id"] for r in rows}), 5)
        lex = {(x["language"], x["lexeme_id"]): x for x in self.data["lexemes"]}
        for row in rows:
            source = lex[(row["language"], row["lexeme_id"])]
            self.assertEqual(row["sense_id"], source["lexeme_id"] + "-S1")
            self.assertEqual(row["source_snapshot"], source["page_url"])
            self.assertEqual(row["id"], ":".join((row["language"], row["lexeme_id"],
                                                   row["sense_id"], row["concept_id"])))
            self.assertTrue(re.fullmatch(r"concept[.]q[1-9][0-9]*", row["concept_id"]))
            self.assertEqual((row["topic"], row["subtopic"], row["level"]),
                             ("family", "kinship", "UNKNOWN"))
            self.assertIsNone(row["level_evidence"])
            self.assertEqual((row["examples"], row["directed_translations"],
                              row["review_status"]), ([], [], "REVIEW_REQUIRED"))
        self.assertEqual({r["concept_id"] for r in rows}, {"concept.q7565", "concept.q1282201"})
        self.assertEqual(lex[("en", "L3624")]["excluded_sense_ids"],
                         ["L3624-S2", "L3624-S3"])
        self.assertEqual(lex[("fr", "L2245")]["excluded_sense_ids"], ["L2245-S2"])

    def test_cross_batch_dedup(self):
        current = {(x["language"], x["lexeme_id"]) for x in self.data["lexemes"]}
        for path in (ROOT / "legal/ledger/evidence").glob("*/candidates.json"):
            if path.parent == FOLDER:
                continue
            other = json.loads(path.read_bytes())
            found = {(x.get("language"), x.get("lexeme_id"))
                     for x in other.get("candidates", [])
                     if x.get("language") and x.get("lexeme_id")}
            self.assertFalse(current & found, f"duplicate source lexeme in {path}")


if __name__ == "__main__":
    unittest.main()
