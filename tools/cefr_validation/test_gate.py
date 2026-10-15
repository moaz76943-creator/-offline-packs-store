import unittest
import json
import tempfile
import subprocess
from pathlib import Path

class GateCLITest(unittest.TestCase):
    def test_gate_cli(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_file = temp_path / "input.jsonl"
            accepted_file = temp_path / "accepted.jsonl"
            rejected_file = temp_path / "rejected.jsonl"

            # Create test data
            valid_evidence = [{
                "source_id": "COE-CEFR-2020",
                "source_version": "2020 Companion volume",
                "source_url": "https://www.coe.int/en/web/common-european-framework-reference-languages/introduction-and-context",
                "locator": "page 10",
                "method": "descriptor_guided_review",
                "reviewer_id": "reviewer-1"
            }]

            rec1 = {
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
                "evidence": valid_evidence
            }

            rec2 = dict(rec1)
            rec2["language"] = "xx" # invalid language

            with open(input_file, 'w', encoding='utf-8') as f:
                f.write(json.dumps(rec1) + "\n")
                f.write(json.dumps(rec2) + "\n")

            # Run CLI
            subprocess.run(["python3", "tools/cefr_validation/gate.py", str(input_file),
                            "--accepted", str(accepted_file),
                            "--rejected", str(rejected_file)], check=True)

            with open(accepted_file, 'r', encoding='utf-8') as f:
                accepted_recs = [json.loads(line) for line in f if line.strip()]

            with open(rejected_file, 'r', encoding='utf-8') as f:
                rejected_recs = [json.loads(line) for line in f if line.strip()]

            self.assertEqual(len(accepted_recs), 1)
            self.assertEqual(accepted_recs[0]["record_id"], "word-1")

            self.assertEqual(len(rejected_recs), 1)
            self.assertIn("Unsupported language ID", rejected_recs[0]["reason"])

if __name__ == '__main__':
    unittest.main()
