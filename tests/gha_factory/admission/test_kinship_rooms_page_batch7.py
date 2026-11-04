"""Revision-pinned Wikidata structured lexemes, never production approval."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "legal/ledger/evidence/wikidata-20261026-kinship-rooms-page-batch7"
EXPECTED = {
    "L615136": ("de", "Wohnzimmer", 2306778967, "Q475018", "home", "rooms", "neuter",
               ["Wohnzimmer", "Wohnzimmers", "Wohnzimmer", "Wohnzimmer", "Wohnzimmer", "Wohnzimmer", "Wohnzimmern", "Wohnzimmer"]),
    "L3330": ("en", "room", 2549975269, "Q180516", "home", "rooms", None,
              ["room", "rooms"]),
    "L4167": ("en", "kitchen", 2550123862, "Q43164", "home", "rooms", None,
              ["kitchen", "kitchens"]),
    "L43711": ("en", "bathroom", 2549778759, "Q190771", "home", "rooms", None,
               ["bathroom", "bathrooms"]),
}


class PinnedKinshipRoomsBatch7(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FOLDER / "candidates.json").read_bytes()
        cls.data = json.loads(cls.raw)
        cls.receipt = json.loads((FOLDER / "receipt.json").read_bytes())

    def test_sha256_canonical_and_actual_rows(self):
        encoded = (json.dumps(self.data, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.assertEqual(self.raw, encoded)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), self.receipt["candidate_sha256"])
        self.assertEqual((len(self.data["candidates"]), len(self.data["lexemes"]),
                          sum(len(x["forms"]) for x in self.data["lexemes"])), (4, 4, 14))
        self.assertEqual((self.receipt["actual_rows"], self.receipt["form_count"]), (4, 14))

    def test_attested_lexemes_forms_and_pinned_revisions(self):
        self.assertEqual(set(EXPECTED), {x["lexeme_id"] for x in self.data["lexemes"]})
        for lex in self.data["lexemes"]:
            lang, lemma, rev, _, _, _, gender, forms = EXPECTED[lex["lexeme_id"]]
            self.assertEqual((lex["language"], lex["lemma"], lex["revision"], lex["gender"]),
                             (lang, lemma, rev, gender))
            self.assertEqual([f["surface"] for f in lex["forms"]], forms)
            self.assertEqual([f["id"] for f in lex["forms"]],
                             [f"{lex['lexeme_id']}-F{i}" for i in range(1, len(forms)+1)])
            self.assertEqual(lex["page_url"],
                             f"https://www.wikidata.org/w/index.php?title=Lexeme:{lex['lexeme_id']}&oldid={rev}")

    def test_concepts_topics_and_unknown_cefr(self):
        for row in self.data["candidates"]:
            lang, _, _, qid, topic, subtopic, _, _ = EXPECTED[row["lexeme_id"]]
            self.assertEqual(row["id"], f"{lang}:{row['lexeme_id']}:{row['lexeme_id']}-S1:concept.{qid.lower()}")
            self.assertEqual(row["concept_evidence"]["item_id"], qid)
            self.assertEqual(row["concept_evidence"]["property"], "P5137")
            self.assertEqual((row["topic"], row["subtopic"], row["level"]),
                             (topic, subtopic, "UNKNOWN"))
            self.assertEqual((row["examples"], row["directed_translations"]), ([], []))
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")

    def test_license_and_no_false_approval(self):
        notice = (ROOT / self.receipt["license_evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(notice).hexdigest(),
                         self.receipt["license_evidence_sha256"])
        self.assertEqual(self.receipt["license_id"], "CC0-1.0")
        self.assertEqual(self.receipt["source_type"], "MANUAL_PAGE_STRUCTURED_EXCERPT_NOT_ORIGINAL_JSON")
        for obj in (self.data, self.receipt):
            for key in ("original_source_bytes_pinned", "source_admission_approved", "production_ready"):
                self.assertIs(obj[key], False)

    def test_cross_batch_sense_dedup(self):
        own = {(r["language"], r["lexeme_id"], r["sense_id"])
               for r in self.data["candidates"]}
        for path in (ROOT / "legal/ledger/evidence").glob("*/candidates.json"):
            if path.parent == FOLDER:
                continue
            for row in json.loads(path.read_bytes()).get("candidates", []):
                self.assertNotIn((row["language"], row["lexeme_id"], row["sense_id"]), own)


if __name__ == "__main__":
    unittest.main()
