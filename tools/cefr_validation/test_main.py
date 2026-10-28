import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

class TestCEFRValidationCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.input_file = Path(self.temp_dir.name) / "input.jsonl"
        self.accepted_file = Path(self.temp_dir.name) / "accepted.jsonl"
        self.rejected_file = Path(self.temp_dir.name) / "rejected.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()

    def get_valid_evidence(self):
        return [{
            "source_id": "COE-CEFR-2020",
            "source_version": "2020 Companion volume",
            "source_url": "https://www.coe.int/en/web/common-european-framework-reference-languages/introduction-and-context",
            "locator": "page 10",
            "method": "descriptor_guided_review",
            "reviewer_id": "reviewer-1"
        }]

    def test_cli_processing_records(self):
        records = [
            {
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
                "evidence": self.get_valid_evidence()
            },
            {
                "record_id": "word-2",
                "language": "xx",  # Invalid language, will be rejected
                "classification_status": "unknown",
                "evidence": []
            }
        ]

        with open(self.input_file, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])

        subprocess.run(
            [
                "python3", "-m", "tools.cefr_validation",
                "--input", str(self.input_file),
                "--accepted", str(self.accepted_file),
                "--rejected", str(self.rejected_file)
            ],
            check=True,
            env=env
        )

        with open(self.accepted_file, "r", encoding="utf-8") as f:
            accepted = [json.loads(line) for line in f if line.strip()]

        with open(self.rejected_file, "r", encoding="utf-8") as f:
            rejected = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["record_id"], "word-1")
        self.assertEqual(accepted[0]["_resolution"], "inferred")

        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["record"]["record_id"], "word-2")
        self.assertIn("Unsupported language ID", rejected[0]["reason"])

if __name__ == '__main__':
    unittest.main()
