"""Seventh pinned derived Wikidata batch: deterministic, review-only and deduplicated."""
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch7")
PRIOR = [Path("legal/ledger/evidence") / x for x in (
    "agent-harvest-20261024", "agent-harvest-20261024-batch2",
    "agent-harvest-20261025-batch3", "agent-harvest-20261025-batch4",
    "agent-harvest-20261025-batch5", "agent-harvest-20261025-batch6")]

class SeventhHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.saved = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.built = c.build(c.ROOT, cls.receipt, folder=FOLDER)
        cls.rows = cls.built["candidates"]

    def test_exact_rebuild_sha_and_counts(self):
        self.assertEqual(c.canonical(self.built), self.saved)
        self.assertEqual(c.digest(self.saved), self.receipt["candidate_sha256"])
        self.assertEqual(len(self.rows), 4)
        self.assertEqual(len(self.receipt["source_files"]), 4)
        self.assertEqual([r["language"] for r in self.rows], ["eu", "eu", "eu", "la"])

    def test_no_duplicate_identity_across_all_seven_batches(self):
        prior = []
        for folder in PRIOR:
            old = c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())
            prior.extend(row["id"] for row in old["candidates"])
        self.assertEqual(len(prior), 218)
        self.assertEqual(len(prior), len(set(prior)))
        self.assertFalse(set(prior).intersection(row["id"] for row in self.rows))

    def test_review_only_unknown_level_no_unverified_translations(self):
        self.assertFalse(self.receipt["production_ready"])
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])
        for row in self.rows:
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])

    def test_fail_closed_for_modified_license_or_source_blob(self):
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, production_ready=True), folder=FOLDER)
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, source_license_evidence_sha256="0"*64), folder=FOLDER)
        tampered = dict(self.receipt, source_files=[dict(x) for x in self.receipt["source_files"]])
        tampered["source_files"][0]["sha256"] = "0"*64
        with self.assertRaises(ValueError):
            c.build(c.ROOT, tampered, folder=FOLDER)

if __name__ == "__main__":
    unittest.main()
