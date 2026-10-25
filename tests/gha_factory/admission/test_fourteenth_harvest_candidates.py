"""Review-only batch 14: pinned Italian lexical senses, no release approval."""
import unittest
from collections import Counter
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch14")
PRIOR = [Path("legal/ledger/evidence") / name for name in (
    "agent-harvest-20261024", "agent-harvest-20261024-batch2",
    *("agent-harvest-20261025-batch%d" % n for n in range(3, 14)),
)]

class FourteenthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.saved = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.built = c.build(c.ROOT, cls.receipt, folder=FOLDER)
        cls.rows = cls.built["candidates"]

    def test_exact_reconstruction_and_sha256(self):
        self.assertEqual(c.canonical(self.built), self.saved)
        self.assertEqual(c.digest(self.saved), self.receipt["candidate_sha256"])
        self.assertEqual(len(self.rows), 2)
        self.assertEqual(len(self.receipt["source_files"]), 2)
        self.assertEqual(Counter(r["language"] for r in self.rows), {"it": 2})
        self.assertEqual({r["topic"] for r in self.rows}, {"religion", "technology"})

    def test_cross_batch_deduplication(self):
        prior = [r["id"] for folder in PRIOR for r in
                 c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())["candidates"]]
        self.assertEqual(len(prior), 282)
        self.assertEqual(len(set(prior)), 282)
        self.assertFalse(set(prior) & {r["id"] for r in self.rows})
        self.assertEqual(len({r["id"] for r in self.rows}), 2)

    def test_review_only_without_invented_claims(self):
        self.assertIs(self.receipt["production_ready"], False)
        self.assertIs(self.receipt["source_admission_approved"], False)
        self.assertIs(self.receipt["original_lexeme_json_pinned"], False)
        self.assertEqual(self.receipt["directed_translations"], 0)
        for row in self.rows:
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
            self.assertEqual(row["source_id"], "wikidata.lexemes")
            self.assertEqual(row["license_id"], "CC0-1.0")

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
