import unittest
import os
import tempfile
import json
from io import StringIO

from tools.lexicon_sanitizer.cli import process_stream
from tools.lexicon_sanitizer.engine import SanitizerEngine, DEFAULT_REGISTRY_PATH

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.engine = SanitizerEngine(registry_path=DEFAULT_REGISTRY_PATH)
        # Ensure en is allowed
        self.engine.valid_languages.add("en")

    def test_process_stream_mixed(self):
        # Create a valid record, a broken json, and an invalid record
        valid_record = {
            "contract_version": "1.0.0",
            "document_id": "doc.en.1",
            "lexemes": [
                {
                    "lexeme_id": "lex.en.1",
                    "language": "en",
                    "lemma": "word",
                    "surface": "word",
                    "pos": "noun"
                }
            ],
            "senses": [
                {
                    "sense_id": "sense.en.1",
                    "concept_id": "concept.1",
                    "definition": "A unit of language."
                }
            ],
            "translations": [{"translation_id": "trans.1"}],
            "examples": [],
            "relations": []
        }

        invalid_record = {"contract_version": "1.0.0"} # Missing everything else
        broken_json = "{\"contract_version\": \"1.0.0\", broken"

        input_lines = [
            json.dumps(valid_record),
            json.dumps(invalid_record),
            broken_json
        ]

        in_stream = StringIO("\n".join(input_lines))
        acc_stream = StringIO()
        rep_stream = StringIO()
        quar_stream = StringIO()
        rev_stream = StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            quar_dir = os.path.join(temp_dir, "quarantined")
            stats = process_stream(
                in_stream, acc_stream, rep_stream, quar_stream, rev_stream, quar_dir, self.engine
            )

            self.assertEqual(stats["total"], 3)
            self.assertEqual(stats["accept"], 1)
            self.assertEqual(stats["quarantine"], 2) # invalid record + broken json
            self.assertEqual(stats["broken_json"], 1)

            # Check that accept stream contains the valid record
            acc_stream.seek(0)
            accepted = json.loads(acc_stream.read().strip())
            self.assertEqual(accepted["document_id"], "doc.en.1")

            # Check that reason files are created in the quarantine directory
            files_in_quar = os.listdir(quar_dir)
            self.assertEqual(len(files_in_quar), 2) # Two reasons files

            for file in files_in_quar:
                self.assertTrue(file.endswith(".reason.txt"))
                with open(os.path.join(quar_dir, file), "r", encoding="utf-8") as rf:
                    content = rf.read()
                    self.assertIn("Reason: ", content)

if __name__ == '__main__':
    unittest.main()
