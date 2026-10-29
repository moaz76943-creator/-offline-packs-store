"""Additional pinned CC0 review candidates; offline integrity checks."""
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261024-batch2")

class AdditionalHarvestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.raw = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.rows = c.build(c.ROOT, cls.receipt, folder=FOLDER)["candidates"]

    def test_exact_reconstruction_and_sha256(self):
        self.assertEqual(c.canonical(c.build(c.ROOT, self.receipt, folder=FOLDER)), self.raw)
        self.assertEqual(c.digest(self.raw), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], 19)
        self.assertEqual(len(self.receipt["source_files"]), 4)

    def test_languages_and_review_only(self):
        counts = {}
        for row in self.rows:
            counts[row["language"]] = counts.get(row["language"], 0) + 1
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
        self.assertEqual(counts, {"en": 18, "es": 1})
        self.assertFalse(self.receipt["production_ready"])
        self.assertFalse(self.receipt["source_admission_approved"])

    def test_no_cross_batch_duplicates(self):
        original = c.strict_json((c.ROOT / c.FOLDER / "candidates.json").read_bytes())["candidates"]
        self.assertFalse({r["id"] for r in original} & {r["id"] for r in self.rows})

    def test_reject_unapproved_promotion(self):
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, production_ready=True), folder=FOLDER)

if __name__ == "__main__":
    unittest.main()
