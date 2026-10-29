"""Fifth pinned review-only lexical candidate batch; no production admission."""
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch5")
PREVIOUS = (c.FOLDER, Path("legal/ledger/evidence/agent-harvest-20261024-batch2"),
            Path("legal/ledger/evidence/agent-harvest-20261025-batch3"),
            Path("legal/ledger/evidence/agent-harvest-20261025-batch4"))

class FifthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.raw = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.rows = c.build(c.ROOT, cls.receipt, folder=FOLDER)["candidates"]

    def test_rebuild_and_source_integrity(self):
        self.assertEqual(c.canonical(c.build(c.ROOT, self.receipt, folder=FOLDER)), self.raw)
        self.assertEqual(c.digest(self.raw), self.receipt["candidate_sha256"])
        self.assertEqual(len(self.rows), 33)
        self.assertEqual(len(self.receipt["source_files"]), 5)

    def test_language_counts_and_review_only(self):
        counts = {}
        for row in self.rows:
            counts[row["language"]] = counts.get(row["language"], 0) + 1
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
        self.assertEqual(counts, {"da": 3, "ml": 16, "pl": 7, "ru": 3, "sv": 4})
        self.assertFalse(self.receipt["production_ready"])
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])

    def test_no_cross_batch_duplicate(self):
        prior = set()
        for folder in PREVIOUS:
            old = c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())
            prior.update(x["id"] for x in old["candidates"])
        self.assertEqual(len(prior), 164)
        self.assertFalse(prior.intersection(x["id"] for x in self.rows))

    def test_tampered_license_and_git_blob_fail_closed(self):
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, production_ready=True), folder=FOLDER)
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, source_license_evidence_sha256="0"*64), folder=FOLDER)
        tampered = dict(self.receipt, source_files=[dict(x) for x in self.receipt["source_files"]])
        tampered["source_files"][0]["origin_git_blob_sha1"] = "0"*40
        with self.assertRaises(ValueError):
            c.build(c.ROOT, tampered, folder=FOLDER)

if __name__ == "__main__":
    unittest.main()
