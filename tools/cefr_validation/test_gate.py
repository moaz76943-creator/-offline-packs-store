import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from tools.cefr_validation.gate import main

class TestGate(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.input_file = Path(self.test_dir.name) / "input.jsonl"
        self.accepted_file = Path(self.test_dir.name) / "accepted.jsonl"
        self.rejected_file = Path(self.test_dir.name) / "rejected.jsonl"

    def tearDown(self):
        self.test_dir.cleanup()

    def test_gate_cli_valid_and_invalid(self):
        # A valid estimated record mapping to A1
        valid_record = {
            "record_id": "word-1",
            "language": "en",
            "classification_status": "estimated",
            "proficiency_framework_id": "CEFR",
            "proficiency_level_id": "A1",
            "skills": {
                "reading": {"mode": "receptive", "status": "unknown"},
                "writing": {"mode": "productive", "status": "unknown"},
                "listening": {"mode": "receptive", "status": "unknown"},
                "speaking": {"mode": "productive", "status": "unknown"}
            },
            "complexity": {
                "word_difficulty": "unknown",
                "sentence_complexity": "unknown",
                "grammar_complexity": "unknown",
                "reading_competence": "unknown"
            },
            "script_literacy": {
                "script_codes": ["Latn"],
                "status": "not_required"
            },
            "topic_domains": [],
            "prerequisites": [],
            "evidence": [{
                "source_id": "COE-CEFR-2020",
                "source_version": "2020 Companion volume",
                "source_url": "https://www.coe.int/en/web/common-european-framework-reference-languages/introduction-and-context",
                "locator": "page 10",
                "method": "descriptor_guided_review",
                "reviewer_id": "reviewer-1"
            }]
        }

        # Invalid record due to missing schema requirements
        invalid_record = {
            "record_id": "word-2",
            "language": "en",
            "classification_status": "unknown"
        }

        # A valid unknown record (since standard schema requires properties even for unknown)
        unknown_record = {
            "record_id": "word-3",
            "language": "en",
            "classification_status": "unknown",
            "proficiency_framework_id": None,
            "proficiency_level_id": None,
            "skills": {
                "reading": {"mode": "receptive", "status": "unknown"},
                "writing": {"mode": "productive", "status": "unknown"},
                "listening": {"mode": "receptive", "status": "unknown"},
                "speaking": {"mode": "productive", "status": "unknown"}
            },
            "complexity": {
                "word_difficulty": "unknown",
                "sentence_complexity": "unknown",
                "grammar_complexity": "unknown",
                "reading_competence": "unknown"
            },
            "script_literacy": {
                "script_codes": ["Latn"],
                "status": "not_required"
            },
            "topic_domains": [],
            "prerequisites": [],
            "evidence": []
        }

        records = [valid_record, invalid_record, unknown_record]

        with open(self.input_file, 'w', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r) + '\n')

        test_args = [
            "gate.py",
            "--input", str(self.input_file),
            "--accepted", str(self.accepted_file),
            "--rejected", str(self.rejected_file)
        ]

        with patch("sys.argv", test_args):
            main()

        with open(self.accepted_file, 'r', encoding='utf-8') as f:
            accepted_lines = [json.loads(line) for line in f]
        with open(self.rejected_file, 'r', encoding='utf-8') as f:
            rejected_lines = [json.loads(line) for line in f]

        self.assertEqual(len(accepted_lines), 2)
        self.assertEqual(len(rejected_lines), 1)

        # check accepted contains word-1 and word-3
        accepted_ids = {r["record_id"] for r in accepted_lines}
        self.assertIn("word-1", accepted_ids)
        self.assertIn("word-3", accepted_ids)

        # check word-1 got _resolution inferred and coarse difficulty beginner
        w1 = next(r for r in accepted_lines if r["record_id"] == "word-1")
        self.assertEqual(w1["_resolution"], "inferred")
        self.assertEqual(w1["_coarse_difficulty"], "beginner")

        # check rejected contains wrapped word-2
        self.assertEqual(rejected_lines[0]["record"]["record_id"], "word-2")
        self.assertIn("Validation error", rejected_lines[0]["reason"])

if __name__ == '__main__':
    unittest.main()
