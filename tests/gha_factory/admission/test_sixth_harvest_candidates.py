"""Sixth pinned review-only lexical batch: SHA256, identities and license gates."""
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c
FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch6")
PRIOR = [Path("legal/ledger/evidence/") / x for x in ("agent-harvest-20261024", "agent-harvest-20261024-batch2", "agent-harvest-20261025-batch3", "agent-harvest-20261025-batch4", "agent-harvest-20261025-batch5")]
class SixthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.raw = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.rows = c.build(c.ROOT, cls.receipt, folder=FOLDER)["candidates"]
    def test_exact_rebuild_and_hashes(self):
        self.assertEqual(c.canonical(c.build(c.ROOT, self.receipt, folder=FOLDER)), self.raw)
        self.assertEqual(c.digest(self.raw), self.receipt["candidate_sha256"])
        self.assertEqual(len(self.rows), 21)
        self.assertEqual(len(self.receipt["source_files"]), 10)
    def test_counts_and_review_only(self):
        counts = {}
        for r in self.rows:
            counts[r["language"]] = counts.get(r["language"], 0) + 1
            self.assertEqual((r["level"], r["review_status"]), ("UNKNOWN", "REVIEW_REQUIRED"))
            self.assertEqual((r["directed_translations"], r["examples"]), ([], []))
        self.assertEqual(counts, {"bg":1,"da":3,"eo":1,"et":2,"ja":2,"ms":2,"pa":3,"sv":5,"ta":1,"uk":1})
        self.assertFalse(self.receipt["production_ready"])
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])
    def test_cross_batch_dedup(self):
        prior = set()
        for folder in PRIOR:
            old = c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())
            prior.update(r["id"] for r in old["candidates"])
        self.assertEqual(len(prior), 197)
        self.assertFalse(prior.intersection(r["id"] for r in self.rows))
    def test_license_and_blob_tampering_fail_closed(self):
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, production_ready=True), folder=FOLDER)
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, source_license_evidence_sha256="0" * 64), folder=FOLDER)
        altered = dict(self.receipt, source_files=[dict(x) for x in self.receipt["source_files"]])
        altered["source_files"][0]["origin_git_blob_sha1"] = "0" * 40
        with self.assertRaises(ValueError):
            c.build(c.ROOT, altered, folder=FOLDER)
if __name__ == "__main__":
    unittest.main()
