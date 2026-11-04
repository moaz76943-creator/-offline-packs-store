"""Batch 17: deduplicated senses from immutable, growing Wikidata harvest shards.

These are REVIEW_REQUIRED derived candidates, not original Lexeme source approval.
"""
import copy
import unittest
from pathlib import Path
from tools.gha_factory.admission import agent_harvest_candidates as c

FOLDER = Path("legal/ledger/evidence/agent-harvest-20261025-batch17")
PRIOR = [Path("legal/ledger/evidence") / name for name in (
    "agent-harvest-20261024", "agent-harvest-20261024-batch2",
    *("agent-harvest-20261025-batch%d" % n for n in range(3, 17)),
)]


class SeventeenthHarvestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / FOLDER / "receipt.json").read_bytes())
        cls.saved = (c.ROOT / FOLDER / "candidates.json").read_bytes()
        cls.built = c.build(c.ROOT, cls.receipt, folder=FOLDER)
        cls.rows = cls.built["candidates"]

    def test_exact_rebuild_sha256_and_source_subset(self):
        self.assertEqual(c.canonical(self.built), self.saved)
        self.assertEqual(c.digest(self.saved), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], 10)
        self.assertEqual(len(self.receipt["source_files"]), 6)
        self.assertEqual(sum(len(s["selected_sense_ids"]) for s in self.receipt["source_files"]), 10)
        for source in self.receipt["source_files"]:
            original = c.strict_json(c.safe_file(c.ROOT, source["path"]).read_bytes())
            self.assertEqual(source["rows"], len(original["rows"]))
            self.assertLess(len(source["selected_sense_ids"]), source["rows"])

    def test_prior_batches_no_duplicate_identity(self):
        prior = [r["id"] for folder in PRIOR for r in
                 c.strict_json((c.ROOT / folder / "candidates.json").read_bytes())["candidates"]]
        self.assertEqual(len(prior), 291)
        self.assertEqual(len(prior), len(set(prior)))
        new = [r["id"] for r in self.rows]
        self.assertEqual(len(new), len(set(new)))
        self.assertFalse(set(prior) & set(new))

    def test_review_only_language_and_topic(self):
        self.assertEqual({lang: sum(r["language"] == lang for r in self.rows)
                          for lang in ("da", "en", "it", "ja", "ru")},
                         {"da": 1, "en": 5, "it": 2, "ja": 1, "ru": 1})
        self.assertEqual({r["topic"] for r in self.rows}, {"colors", "time"})
        for row in self.rows:
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["original_lexeme_json_pinned"])
        self.assertFalse(self.receipt["production_ready"])

    def test_invalid_selection_fails_closed(self):
        for selected in ([], ["L999999-S1"], ["L1355107-S1", "L1355107-S1"],
                         "L1355107-S1", ["not-a-sense"]):
            bad = copy.deepcopy(self.receipt)
            bad["source_files"][0]["selected_sense_ids"] = selected
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                c.build(c.ROOT, bad, folder=FOLDER)

    def test_source_license_and_status_tamper_fails_closed(self):
        for field, value in (("production_ready", True),
                             ("source_admission_approved", True),
                             ("source_license_evidence_sha256", "0"*64)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.build(c.ROOT, dict(self.receipt, **{field: value}), folder=FOLDER)
        bad = copy.deepcopy(self.receipt)
        bad["source_files"][0]["origin_git_blob_sha1"] = "0"*40
        with self.assertRaises(ValueError):
            c.build(c.ROOT, bad, folder=FOLDER)


if __name__ == "__main__":
    unittest.main()
