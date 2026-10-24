"""Fourth pinned Wikidata-derived candidate batch: source integrity and review-only admission."""
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch4")

class FourthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.raw = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.rows = c.build(c.ROOT, cls.receipt, folder=FOLDER)["candidates"]

    def test_source_reconstruction_and_sha256(self):
        self.assertEqual(c.canonical(c.build(c.ROOT, self.receipt, folder=FOLDER)), self.raw)
        self.assertEqual(c.digest(self.raw), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], 12)
        self.assertEqual(len(self.receipt["source_files"]), 5)

    def test_languages_and_no_invented_levels_or_translations(self):
        counts = {}
        for row in self.rows:
            counts[row["language"]] = counts.get(row["language"], 0) + 1
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
        self.assertEqual(counts, {"cs": 5, "da": 3, "en": 1, "it": 1, "ru": 2})
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["production_ready"])
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])

    def test_no_cross_batch_duplicates(self):
        seen = set()
        for folder in (c.FOLDER, Path("legal/ledger/evidence/agent-harvest-20261024-batch2"), Path("legal/ledger/evidence/agent-harvest-20261025-batch3")):
            previous = c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())
            seen.update(r["id"] for r in previous["candidates"])
        self.assertFalse(seen.intersection(r["id"] for r in self.rows))

    def test_fail_closed_on_license_or_origin_tampering(self):
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, production_ready=True), folder=FOLDER)
        with self.assertRaises(ValueError):
            c.build(c.ROOT, dict(self.receipt, source_license_evidence_sha256="0"*64), folder=FOLDER)
        modified = dict(self.receipt, source_files=[dict(s) for s in self.receipt["source_files"]])
        modified["source_files"][0]["origin_git_blob_sha1"] = "0"*40
        with self.assertRaises(ValueError):
            c.build(c.ROOT, modified, folder=FOLDER)

if __name__ == "__main__":
    unittest.main()
