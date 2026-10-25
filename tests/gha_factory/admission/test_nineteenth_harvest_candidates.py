"""Batch 19: one newly harvested English sense, source-pinned and review-only."""
import copy
import unittest
from pathlib import Path

from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261026-batch19")
PRIOR = [Path("legal/ledger/evidence") / name for name in (
    "agent-harvest-20261024", "agent-harvest-20261024-batch2",
    *("agent-harvest-20261025-batch%d" % n for n in range(3, 19)),
)]


class NineteenthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.saved = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.built = c.build(c.ROOT, cls.receipt, folder=FOLDER)

    def test_exact_source_reconstruction_and_sha256(self):
        self.assertEqual(c.canonical(self.built), self.saved)
        self.assertEqual(c.digest(self.saved), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], 1)
        source = self.receipt["source_files"][0]
        raw = c.safe_file(c.ROOT, source["path"]).read_bytes()
        self.assertEqual(c.digest(raw), source["sha256"])
        self.assertEqual(len(c.strict_json(raw)["rows"]), source["rows"])
        self.assertEqual(source["selected_sense_ids"], ["L25439-S1"])

    def test_new_attested_identity_not_in_prior_batches(self):
        rows = self.built["candidates"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["language"], row["lemma"], row["sense_id"]),
                         ("en", "scorn", "L25439-S1"))
        self.assertEqual(row["forms"], ["scorn", "scorns"])
        self.assertEqual(row["concept_id"], "concept.q19358081")
        prior = [item["id"] for folder in PRIOR for item in
                 c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())["candidates"]]
        self.assertEqual(len(prior), len(set(prior)))
        self.assertNotIn(row["id"], prior)

    def test_no_false_approval_or_invented_level(self):
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["production_ready"])
        row = self.built["candidates"][0]
        self.assertEqual(row["level"], "UNKNOWN")
        self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
        self.assertEqual(row["directed_translations"], [])
        self.assertEqual(row["examples"], [])

    def test_tampered_source_or_false_approval_rejected(self):
        bad = copy.deepcopy(self.receipt)
        bad["source_files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            c.build(c.ROOT, bad, folder=FOLDER)
        bad = copy.deepcopy(self.receipt)
        bad["source_files"][0]["selected_sense_ids"] = ["L999999-S1"]
        with self.assertRaises(ValueError):
            c.build(c.ROOT, bad, folder=FOLDER)
        for field in ("production_ready", "source_admission_approved"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.build(c.ROOT, dict(self.receipt, **{field: True}), folder=FOLDER)


if __name__ == "__main__":
    unittest.main()
