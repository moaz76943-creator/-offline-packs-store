"""Review-only Spanish cocina: three attested, distinct senses; no release claims."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-spanish-kitchen-batch8"
EXPECTED = {"L312834-S1": ("Q43164", "home", "rooms"),
            "L312834-S2": ("Q182995", "food", "cooking_equipment"),
            "L312834-S3": ("Q2111686", "activities", "cooking")}

class SpanishKitchenBatch8(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_bytes = (FOLDER / "source_excerpt.json").read_bytes()
        cls.candidate_bytes = (FOLDER / "candidates.json").read_bytes()
        cls.source = json.loads(cls.source_bytes)
        cls.data = json.loads(cls.candidate_bytes)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_canonical_sha256_counts_and_license(self):
        for name, raw, expected in (
            ("source_excerpt_sha256", self.source_bytes, self.source),
            ("candidate_sha256", self.candidate_bytes, self.data)):
            canonical = (json.dumps(expected, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False) + "\n").encode()
            self.assertEqual(raw, canonical)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), self.receipt[name])
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(), self.receipt["license_evidence_sha256"])
        self.assertEqual((self.receipt["actual_rows"], self.receipt["lexeme_count"],
                          self.receipt["form_count"]), (3, 1, 2))
        self.assertEqual(len(self.data["candidates"]), 3)

    def test_pinned_lexeme_forms_and_concept_senses(self):
        src = self.source["lexeme"]
        lex = self.data["lexemes"][0]
        self.assertEqual((src["lexeme_id"], src["language"], src["language_qid"],
                          src["lexical_category_qid"], src["lemma"], src["gender_qid"]),
                         ("L312834", "es", "Q1321", "Q1084", "cocina", "Q1775415"))
        self.assertEqual((lex["gender"], lex["lemma"], lex["revision"]),
                         ("feminine", "cocina", 2402636370))
        self.assertEqual([f["surface"] for f in lex["forms"]], ["cocina", "cocinas"])
        self.assertEqual([f["id"] for f in lex["forms"]],
                         [f["id"] for f in src["forms"]])
        self.assertEqual({s["id"]: s["concept_qid"] for s in src["senses"]},
                         {k: v[0] for k, v in EXPECTED.items()})
        for row in self.data["candidates"]:
            qid, topic, subtopic = EXPECTED[row["sense_id"]]
            self.assertEqual((row["concept_evidence"]["item_id"], row["topic"],
                              row["subtopic"], row["level"]), (qid, topic, subtopic, "UNKNOWN"))
            self.assertEqual(row["id"],
                             f"es:L312834:{row['sense_id']}:concept.{qid.lower()}")
            self.assertEqual(row["source_snapshot"], self.receipt["source_page"])

    def test_review_only_and_no_fabricated_content(self):
        for obj in (self.data, self.receipt):
            for field in ("original_source_bytes_pinned",
                          "source_admission_approved", "production_ready"):
                self.assertIs(obj[field], False)
        self.assertEqual(self.receipt["source_type"],
                         "DERIVED_STRUCTURED_EXCERPT_NOT_ORIGINAL_JSON")
        self.assertEqual(self.source["extraction_kind"],
                         "DERIVED_STRUCTURED_FIELDS_NOT_ORIGINAL_ENTITYDATA")
        for row in self.data["candidates"]:
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
            self.assertIsNone(row["level_evidence"])

    def test_no_duplicate_sense_in_any_other_batch(self):
        own = {(r["language"], r["lexeme_id"], r["sense_id"])
               for r in self.data["candidates"]}
        self.assertEqual(len(own), 3)
        for path in (ROOT / "legal/ledger/evidence").glob("*/candidates.json"):
            if path.parent == FOLDER:
                continue
            for row in json.loads(path.read_bytes()).get("candidates", []):
                self.assertNotIn((row["language"], row["lexeme_id"], row["sense_id"]),
                                 own, str(path))

if __name__ == "__main__":
    unittest.main()
