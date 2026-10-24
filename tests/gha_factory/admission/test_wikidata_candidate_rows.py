"""Exact-evidence QA for independently keyed review-only Wikidata rows."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.gha_factory.admission.review_only_wikidata import DEFAULT_CANDIDATE, build
from tools.gha_factory.admission.wikidata_candidate_rows import DEFAULT_ROWS, flatten, main
from tools.gha_factory.admission.review_only_wikidata import ReviewError

ROOT = Path(__file__).resolve().parents[3]


class ReviewRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = build(ROOT)
        cls.generated = flatten(cls.inventory)
        cls.committed = json.loads((ROOT / DEFAULT_ROWS).read_text(encoding="utf-8"))

    def test_exact_replay_matches_committed_rows(self):
        self.assertEqual(self.generated, self.committed)
        self.assertEqual(main(["--repo-root", str(ROOT)]), 0)

    def test_actual_rows_and_language_counts(self):
        self.assertEqual(self.generated["summary"], {
            "lexemes": 3, "senses": 25, "forms": 40,
            "attested_concept_links": 1, "actual_rows": 68,
            "languages": ["ar", "de", "en"],
        })
        self.assertEqual(len({r["row_id"] for r in self.generated["rows"]}), 68)
        self.assertEqual({lang: sum(r["language"] == lang for r in self.generated["rows"])
                          for lang in ("ar", "de", "en")}, {"ar": 5, "de": 38, "en": 25})

    def test_no_fictitious_levels_topics_translations_or_publication(self):
        self.assertEqual(self.generated["status"], "REVIEW_REQUIRED")
        self.assertIs(self.generated["publication_approved"], False)
        for row in self.generated["rows"]:
            self.assertEqual(row["source_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["license_id"], "CC0-1.0")
            self.assertIs(row["publication_approved"], False)
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["level_framework"], "UNKNOWN")
            self.assertIsNone(row["topic_id"])
            self.assertIsNone(row["subtopic_id"])
            self.assertNotIn("translation", row)
            self.assertNotIn("example", row)
            self.assertEqual(len(row["source_artifact_sha256"]), 64)

    def test_only_attested_concept_and_grammar_qids(self):
        senses = [r for r in self.generated["rows"] if r["row_type"] == "sense"]
        forms = [r for r in self.generated["rows"] if r["row_type"] == "form"]
        links = [(r["row_id"], q) for r in senses for q in r["attested"]["concept_qids"]]
        self.assertEqual(links, [("L1026-S1", "Q25443024")])
        self.assertEqual(len(forms), 40)
        self.assertTrue(all(isinstance(r["attested"]["grammatical_feature_qids"], list)
                            for r in forms))

    def test_modified_source_status_and_guessed_cefr_fail(self):
        bad = copy.deepcopy(self.inventory)
        bad["lexemes"][0]["source_status"] = "APPROVED_FOR_REDISTRIBUTION"
        with self.assertRaisesRegex(ReviewError, "rights/status"):
            flatten(bad)
        bad = copy.deepcopy(self.inventory)
        bad["lexemes"][0]["level_status"] = "A1"
        with self.assertRaisesRegex(ReviewError, "unsupported enrichment"):
            flatten(bad)

    def test_duplicates_and_counts_fail_closed(self):
        bad = copy.deepcopy(self.inventory)
        bad["lexemes"][0]["forms"].append(copy.deepcopy(bad["lexemes"][0]["forms"][0]))
        with self.assertRaisesRegex(ReviewError, "duplicate"):
            flatten(bad)
        bad = copy.deepcopy(self.inventory)
        bad["summary"]["forms"] += 1
        with self.assertRaisesRegex(ReviewError, "count mismatch"):
            flatten(bad)

    def test_source_provenance_and_candidate_tampering_detected(self):
        bad = copy.deepcopy(self.inventory)
        bad["lexemes"][0]["source_artifact_sha256"] = "not-sha"
        with self.assertRaisesRegex(ReviewError, "pinned evidence"):
            flatten(bad)
        altered = copy.deepcopy(self.committed)
        altered["rows"][0]["attested"]["lemma"] = "invented"
        self.assertNotEqual(altered, flatten(build(ROOT)))

    def test_output_path_escape_and_overwrite_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("tools.gha_factory.admission.wikidata_candidate_rows.build",
                       return_value=self.inventory), patch(
                "tools.gha_factory.admission.wikidata_candidate_rows.confined",
                side_effect=ReviewError("unsafe review artifact path")
            ):
                self.assertEqual(main(["--repo-root", str(root),
                                       "--output", "../escape.json",
                                       "--write-new"]), 2)


if __name__ == "__main__":
    unittest.main()
