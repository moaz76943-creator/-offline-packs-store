"""Review-only batch 13: source integrity, deduplication, and fail-closed admission."""
import unittest
from collections import Counter
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch13")
PRIOR = [Path("legal/ledger/evidence") / name for name in (
    "agent-harvest-20261024", "agent-harvest-20261024-batch2",
    *("agent-harvest-20261025-batch%d" % n for n in range(3, 13)),
)]

class ThirteenthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.saved = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.built = c.build(c.ROOT, cls.receipt, folder=FOLDER)
        cls.rows = cls.built["candidates"]

    def test_exact_reconstruction_and_sha256(self):
        self.assertEqual(c.canonical(self.built), self.saved)
        self.assertEqual(c.digest(self.saved), self.receipt["candidate_sha256"])
        self.assertEqual(len(self.rows), 7)
        self.assertEqual(len(self.receipt["source_files"]), 6)
        self.assertEqual(Counter(r["language"] for r in self.rows),
                         {"de": 2, "fr": 1, "it": 1, "ml": 1, "pl": 1, "ru": 1})

    def test_cross_batch_deduplication(self):
        prior = [r["id"] for folder in PRIOR for r in
                 c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())["candidates"]]
        self.assertEqual(len(prior), 275)
        self.assertEqual(len(set(prior)), 275)
        self.assertFalse(set(prior) & {r["id"] for r in self.rows})
        self.assertEqual(len({r["id"] for r in self.rows}), 7)

    def test_review_only_without_invented_claims(self):
        self.assertIs(self.receipt["production_ready"], False)
        self.assertIs(self.receipt["source_admission_approved"], False)
        self.assertIs(self.receipt["original_lexeme_json_pinned"], False)
        for row in self.rows:
            self.assertIn(row["topic"], ("numbers", "clothing", "health"))
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])

    def test_integrity_and_approval_fail_closed(self):
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, production_ready=True), folder=FOLDER)
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, source_license_evidence_sha256="0"*64), folder=FOLDER)
        bad = dict(self.receipt, source_files=[dict(x) for x in self.receipt["source_files"]])
        bad["source_files"][0]["origin_git_blob_sha1"] = "0"*40
        with self.assertRaises(ValueError):
            c.build(c.ROOT, bad, folder=FOLDER)

if __name__ == "__main__":
    unittest.main()
