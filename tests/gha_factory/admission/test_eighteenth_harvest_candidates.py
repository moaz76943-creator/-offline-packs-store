"""Batch 18: remaining attested color senses from pinned derived harvest snapshots.

These two rows are REVIEW_REQUIRED, not independently source-admitted.
"""
import copy
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch18")
PRIOR = [Path("legal/ledger/evidence") / name for name in (
    "agent-harvest-20261024", "agent-harvest-20261024-batch2",
    *("agent-harvest-20261025-batch%d" % n for n in range(3, 18)),
)]


class EighteenthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.saved = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.built = c.build(c.ROOT, cls.receipt, folder=FOLDER)
        cls.rows = cls.built["candidates"]

    def test_exact_source_reconstruction_and_sha256(self):
        self.assertEqual(c.canonical(self.built), self.saved)
        self.assertEqual(c.digest(self.saved), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], 2)
        self.assertEqual(len(self.receipt["source_files"]), 2)
        for src in self.receipt["source_files"]:
            original = c.strict_json(c.safe_file(c.ROOT, src["path"]).read_bytes())
            self.assertEqual(src["rows"], len(original["rows"]))
            self.assertEqual(len(src["selected_sense_ids"]), 1)
            self.assertGreater(src["rows"], 1)

    def test_no_cross_batch_identity_duplicates(self):
        prior = [row["id"] for folder in PRIOR for row in
                 c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())["candidates"]]
        self.assertEqual(len(prior), 301)
        self.assertEqual(len(prior), len(set(prior)))
        new = [row["id"] for row in self.rows]
        self.assertEqual(len(new), 2)
        self.assertFalse(set(new) & set(prior))

    def test_review_only_no_unattested_translation_or_cefr(self):
        self.assertEqual({r["language"]: r["lemma"] for r in self.rows},
                         {"en": "wine", "it": "vinaccia"})
        self.assertEqual({r["concept_id"] for r in self.rows}, {"concept.q3014419"})
        for row in self.rows:
            self.assertEqual(row["topic"], "colors")
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
        self.assertFalse(self.receipt["production_ready"])
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])

    def test_invalid_source_selection_and_false_approval_rejected(self):
        for value in ([], ["L999999-S1"], ["L4710-S2", "L4710-S2"]):
            bad = copy.deepcopy(self.receipt)
            bad["source_files"][0]["selected_sense_ids"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.build(c.ROOT, bad, folder=FOLDER)
        for field in ("production_ready", "source_admission_approved"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.build(c.ROOT, dict(self.receipt, **{field: True}), folder=FOLDER)


if __name__ == "__main__":
    unittest.main()
