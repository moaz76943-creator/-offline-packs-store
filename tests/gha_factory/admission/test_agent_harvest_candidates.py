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
        self.assertEqual(self.receipt["actual_rows"], 115)

    def test_languages_topics_unknown_levels_and_no_translation(self):
        rows = c.build(self.root, self.receipt)["candidates"]
        counts = {}
        for r in rows:
            counts[r["language"]] = counts.get(r["language"], 0) + 1
            self.assertIn(r["topic"], ("food", "work", "health", "city", "clothing", "colors", "animals"))
            self.assertEqual(r["level"], "UNKNOWN")
            self.assertEqual(r["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(r["directed_translations"], [])
            self.assertEqual(r["examples"], [])
        self.assertEqual(counts, {"de": 27, "en": 32, "es": 11, "fr": 27, "it": 7, "ja": 6, "pt": 1, "ru": 4})

    def test_extended_source_receipts_pinned_to_one_commit(self):
        self.assertEqual(self.receipt["source_commit"], "2ac92fbf1521a617db59dede784163b939c811e6")
        self.assertEqual(len(self.receipt["source_files"]), 23)
        self.assertEqual(sum(s["rows"] for s in self.receipt["source_files"]), 115)

    def test_refuse_false_approval(self):
        with self.assertRaises(ValueError):
            c.build(self.root, dict(self.receipt, production_ready=True))

    def test_refuse_changed_source_hash(self):
        bad = dict(self.receipt, source_files=[dict(s) for s in self.receipt["source_files"]])
        bad["source_files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            c.build(self.root, bad)

    def test_reject_forged_source_license_and_origin_receipts(self):
        # A forged receipt must not be able to claim approval by substituting
        # a different license notice, source branch, or arbitrary origin path.
        for field, value in (
            ("source_license", "CC-BY-SA-4.0"),
            ("source_branch", "untrusted"),
            ("source_commit", "not-a-commit"),
            ("original_lexeme_json_pinned", True),
            ("source_license_evidence_path", "legal/ledger/sources.json"),
            ("source_license_evidence_sha256", "0" * 64),
            ("source_files", []),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.build(self.root, dict(self.receipt, **{field: value}))
        bad = dict(self.receipt, source_files=[dict(s) for s in self.receipt["source_files"]])
        bad["source_files"][0]["origin_path"] = "data/agents/harvest/wikidata/en/work.json"
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
