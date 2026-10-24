"""Real pinned multilingual harvest candidate checks (no network)."""
import json
import unittest
from tools.gha_factory.admission import agent_harvest_candidates as c


class HarvestCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = c.ROOT
        cls.receipt = c.strict_json((cls.root / c.FOLDER / "receipt.json").read_bytes())

    def test_exact_export_and_sha256(self):
        raw = (self.root / c.FOLDER / "candidates.json").read_bytes()
        self.assertEqual(c.canonical(c.build(self.root, self.receipt)), raw)
        self.assertEqual(c.digest(raw), self.receipt["candidate_sha256"])
        self.assertEqual(self.receipt["actual_rows"], 42)

    def test_languages_topics_unknown_levels_and_no_translation(self):
        rows = c.build(self.root, self.receipt)["candidates"]
        counts = {}
        for r in rows:
            counts[r["language"]] = counts.get(r["language"], 0) + 1
            self.assertIn(r["topic"], ("food", "work", "health"))
            self.assertEqual(r["level"], "UNKNOWN")
            self.assertEqual(r["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(r["directed_translations"], [])
            self.assertEqual(r["examples"], [])
        self.assertEqual(counts, {"de": 14, "en": 10, "es": 4, "fr": 14})

    def test_refuse_false_approval(self):
        with self.assertRaises(ValueError):
            c.build(self.root, dict(self.receipt, production_ready=True))

    def test_refuse_changed_source_hash(self):
        bad = dict(self.receipt, source_files=[dict(s) for s in self.receipt["source_files"]])
        bad["source_files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            c.build(self.root, bad)

    def test_reject_duplicate_json_property(self):
        with self.assertRaises(ValueError):
            c.strict_json(b'{"a":1,"a":2}')

    def test_ledger_still_empty(self):
        ledger = json.loads((self.root / "legal/ledger/sources.json").read_text())
        self.assertEqual(ledger["sources"], [])
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["production_ready"])


if __name__ == "__main__":
    unittest.main()
