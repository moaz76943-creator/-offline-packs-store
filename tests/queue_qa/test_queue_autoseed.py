import json
import os
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.queue_autoseed.autoseed_manager import autoseed_queue

class TestQueueAutoseed(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger_path = os.path.join(self.temp_dir.name, "sources.json")
        self.queue_path = os.path.join(self.temp_dir.name, "queue.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_approved_sources_autoseed_successfully(self):
        ledger_data = {
            "sources": [
                {
                    "source_id": "kaikki_de_deu_core",
                    "canonical_url": "https://kaikki.org",
                    "license_id": "CC-BY-SA-4.0",
                    "review_decision": "APPROVED"
                },
                {
                    "source_id": "quarantined_sample",
                    "review_decision": "QUARANTINED"
                }
            ]
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(ledger_data, f)

        ok, msg, tasks = autoseed_queue(self.ledger_path, self.queue_path)
        self.assertTrue(ok)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['source_id'], "kaikki_de_deu_core")
        self.assertEqual(tasks[0]['status'], "QUEUED")

    def test_zero_approved_sources_fails_closed(self):
        ledger_data = {"sources": [{"source_id": "unapproved", "review_decision": "PENDING"}]}
        with open(self.ledger_path, 'w') as f:
            json.dump(ledger_data, f)

        ok, msg, tasks = autoseed_queue(self.ledger_path, self.queue_path)
        self.assertFalse(ok)
        self.assertIn("NO_APPROVED_SOURCES_FOUND", msg)

if __name__ == "__main__":
    unittest.main()
