"""Third batch of pinned Wikidata-derived candidates: review-only and source-hash verified."""
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch3")

class ThirdHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.raw = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.rows = c.build(c.ROOT, cls.receipt, folder=FOLDER)["candidates"]

    def test_exact_export_and_sha256(self):
        self.assertEqual(c.canonical(c.build(c.ROOT, self.receipt, folder=FOLDER)), self.raw)
        self.assertEqual(c.digest(self.raw), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], 18)
        self.assertEqual(len(self.receipt["source_files"]), 14)

    def test_real_languages_and_review_only(self):
        counts = {}
        for row in self.rows:
            counts[row["language"]] = counts.get(row["language"], 0) + 1
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
        self.assertEqual(counts, {'cs': 2,'da': 1,'es': 1,'it': 1,'ja': 1,'ko': 1,'ml': 1,'nl': 1,'pt': 1,'ru': 1,'sv': 3,'tr': 1,'uk': 2,'vi': 1})
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["production_ready"])
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])

    def test_no_cross_batch_identity_collision(self):
        previous = set()
        for folder in (c.FOLDER, Path("legal/ledger/evidence/agent-harvest-20261024-batch2")):
            old = c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())
            previous.update(row["id"] for row in old["candidates"])
        self.assertFalse(previous.intersection(row["id"] for row in self.rows))

    def test_reject_tampered_hash_or_false_approval(self):
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, production_ready=True), folder=FOLDER)
        modified = dict(self.receipt, source_files=[dict(s) for s in self.receipt["source_files"]])
        modified["source_files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            c.build(c.ROOT, modified, folder=FOLDER)

if __name__ == "__main__":
    unittest.main()
