"""Review-only batch 16: last unpinned Punjabi harvested animal sense.

Source attestation is structural, not independent linguistic QA or source admission.
"""
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch16")
PRIOR = [Path("legal/ledger/evidence") / name for name in (
    "agent-harvest-20261024", "agent-harvest-20261024-batch2",
    *("agent-harvest-20261025-batch%d" % n for n in range(3, 16)),
)]

class SixteenthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.saved = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.built = c.build(c.ROOT, cls.receipt, folder=FOLDER)
        cls.rows = cls.built["candidates"]

    def test_rebuild_and_integrity(self):
        self.assertEqual(c.canonical(self.built), self.saved)
        self.assertEqual(c.digest(self.saved), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], 1)
        self.assertEqual(self.receipt["source_files"][0]["rows"], 1)

    def test_cross_batch_deduplication(self):
        prior = [r["id"] for folder in PRIOR for r in
                 c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())["candidates"]]
        self.assertEqual(len(prior), 290)
        self.assertEqual(len(prior), len(set(prior)))
        self.assertFalse(set(prior) & {r["id"] for r in self.rows})

    def test_source_attestation_not_language_approval(self):
        row, = self.rows
        self.assertEqual(row["language"], "pa")
        self.assertEqual(row["topic"], "animals")
        self.assertEqual(row["lexeme_id"], "L1011425")
        self.assertEqual(row["sense_id"], "L1011425-S8")
        self.assertEqual(row["wikidata"], "Q7367")
        self.assertEqual(row["forms"], ["در", "ਦਰ", "دراں", "ਦਰਾਂ", "دروں", "ਦਰੋਂ"])
        self.assertEqual(row["level"], "UNKNOWN")
        self.assertEqual(row["directed_translations"], [])
        self.assertEqual(row["examples"], [])
        self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
        self.assertFalse(self.receipt["production_ready"])
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])
        self.assertEqual(self.receipt["linguistic_qa_status"], "SUSPECT_MISMATCH")

    def test_fail_closed_source_or_license_tampering(self):
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
