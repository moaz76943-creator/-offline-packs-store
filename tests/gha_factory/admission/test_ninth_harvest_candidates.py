"""Ninth pinned Wikidata-derived time candidate batch: provenance and QC gates."""
import unittest
from collections import Counter
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch9")
PRIOR = [Path("legal/ledger/evidence") / name for name in (
    "agent-harvest-20261024", "agent-harvest-20261024-batch2",
    "agent-harvest-20261025-batch3", "agent-harvest-20261025-batch4",
    "agent-harvest-20261025-batch5", "agent-harvest-20261025-batch6",
    "agent-harvest-20261025-batch7", "agent-harvest-20261025-batch8")]

class NinthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.saved = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.built = c.build(c.ROOT, cls.receipt, folder=FOLDER)
        cls.rows = cls.built["candidates"]

    def test_exact_rebuild_and_sha256(self):
        self.assertEqual(c.canonical(self.built), self.saved)
        self.assertEqual(c.digest(self.saved), self.receipt["candidate_sha256"])
        self.assertEqual(len(self.rows), 13)
        self.assertEqual(len(self.receipt["source_files"]), 4)
        self.assertEqual(Counter(r["language"] for r in self.rows),
                         {"de": 5, "en": 5, "es": 1, "fr": 2})

    def test_cross_batch_deduplication(self):
        old = [row["id"] for folder in PRIOR for row in
               c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())["candidates"]]
        self.assertEqual(len(old), 235)
        self.assertEqual(len(old), len(set(old)))
        self.assertFalse(set(old) & {row["id"] for row in self.rows})
        self.assertEqual(len({row["id"] for row in self.rows}), 13)

    def test_review_only_no_fabricated_claims(self):
        self.assertIs(self.receipt["production_ready"], False)
        self.assertIs(self.receipt["source_admission_approved"], False)
        self.assertIs(self.receipt["original_lexeme_json_pinned"], False)
        for row in self.rows:
            self.assertEqual(row["topic"], "time")
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])

    def test_source_integrity_fail_closed(self):
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, production_ready=True), folder=FOLDER)
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, source_license_evidence_sha256="0"*64), folder=FOLDER)
        bad = dict(self.receipt, source_files=[dict(s) for s in self.receipt["source_files"]])
        bad["source_files"][0]["origin_git_blob_sha1"] = "0"*40
        with self.assertRaises(ValueError):
            c.build(c.ROOT, bad, folder=FOLDER)

if __name__ == "__main__":
    unittest.main()
