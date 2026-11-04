"""Review-only kinship page batch: source-attested forms, provenance, and dedup."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-kinship-page-batch9"
EXPECTED = {
    "L320495": ("en", "father-in-law", 2552394065, "Q13204680",
                ("father-in-law", "fathers-in-law")),
    "L325004": ("en", "papa", 2549906667, "Q7565", ("papa", "papas")),
    "L691896": ("fr", "arrière-grand-père", 2510450820, "Q2500621",
                ("arrière-grand-père", "arrière-grands-pères")),
}

class KinshipPageBatch9(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_raw = (FOLDER / "source_excerpt.json").read_bytes()
        cls.candidate_raw = (FOLDER / "candidates.json").read_bytes()
        cls.source = json.loads(cls.source_raw)
        cls.data = json.loads(cls.candidate_raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_canonical_hashes_and_license(self):
        for obj, raw, key in ((self.source, self.source_raw, "source_excerpt_sha256"),
                              (self.data, self.candidate_raw, "candidate_sha256")):
            canonical = (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False) + "\n").encode()
            self.assertEqual(raw, canonical)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), self.receipt[key])
        self.assertEqual(self.receipt["license_evidence_path"],
                         "legal/source_evidence/wikidata-structured-cc0.txt")
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(),
                         self.receipt["license_evidence_sha256"])
        self.assertIn(b"Lexeme and EntitySchema namespaces ONLY.", notice)

    def test_exact_lexemes_forms_and_concept_provenance(self):
        self.assertEqual(len(self.source["lexemes"]), 3)
        self.assertEqual(len(self.data["candidates"]), 3)
        self.assertEqual((self.receipt["actual_rows"], self.receipt["form_count"]), (3, 6))
        lexemes = {x["lexeme_id"]: x for x in self.source["lexemes"]}
        exported = {x["lexeme_id"]: x for x in self.data["lexemes"]}
        for lex_id, (lang, lemma, rev, qid, forms) in EXPECTED.items():
            src = lexemes[lex_id]
            exp = exported[lex_id]
            self.assertEqual((src["language"], src["lemma"], src["revision"]),
                             (lang, lemma, rev))
            self.assertEqual([x["surface"] for x in src["forms"]], list(forms))
            self.assertEqual(exp["forms"], src["forms"])
            self.assertEqual(exp["revision"], rev)
            self.assertEqual(src["senses"], [{"id": lex_id + "-S1", "concept_qid": qid}])
            self.assertIn("oldid=" + str(rev), src["source_page"])
        self.assertEqual(exported["L325004"]["register"], "informal")
        self.assertEqual(exported["L691896"]["grammatical_gender"], "masculine")

    def test_candidates_reference_exact_source_senses(self):
        lexemes = {x["lexeme_id"]: x for x in self.source["lexemes"]}
        for row in self.data["candidates"]:
            src = lexemes[row["lexeme_id"]]
            sense = src["senses"][0]
            self.assertEqual(row["id"],
                             f'{src["language"]}:{src["lexeme_id"]}:{sense["id"]}:concept.{sense["concept_qid"].lower()}')
            self.assertEqual(row["concept_evidence"]["item_id"], sense["concept_qid"])
            self.assertEqual(row["concept_evidence"]["property"], "P5137")
            self.assertEqual(row["source_snapshot"], src["source_page"])
            self.assertEqual((row["topic"], row["subtopic"], row["level"]),
                             ("family", "kinship", "UNKNOWN"))

    def test_review_only_and_no_fabricated_content(self):
        self.assertEqual(self.source["extraction_kind"],
                         "DERIVED_STRUCTURED_FIELDS_NOT_ORIGINAL_ENTITYDATA")
        for obj in (self.data, self.receipt):
            for field in ("original_source_bytes_pinned", "source_admission_approved",
                          "production_ready"):
                self.assertIs(obj[field], False)
        for row in self.data["candidates"]:
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
            self.assertIsNone(row["level_evidence"])

    def test_no_duplicate_sense_across_candidate_batches(self):
        own = {(x["language"], x["lexeme_id"], x["sense_id"])
               for x in self.data["candidates"]}
        self.assertEqual(len(own), 3)
        for path in (ROOT / "legal/ledger/evidence").glob("*/candidates.json"):
            if path.parent == FOLDER:
                continue
            for row in json.loads(path.read_bytes()).get("candidates", []):
                self.assertNotIn((row["language"], row["lexeme_id"], row["sense_id"]),
                                 own, str(path))

if __name__ == "__main__":
    unittest.main()
