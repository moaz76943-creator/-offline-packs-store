import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.queue_autoseed.autoseed_manager import generate_queue_tasks

class TestAutoseedManager(unittest.TestCase):
    def test_generate_tasks_from_approved_source(self):
        sources = {
            "approved_sources": [
                {
                    "source_id": "kaikki_de_deu_core",
                    "legal_review_status": "APPROVED",
                    "sha256": "1234567890abcdef"
                },
                {
                    "source_id": "unapproved_source",
                    "legal_review_status": "PENDING_REVIEW",
                    "sha256": "0000"
                }
            ]
        }
        tasks = generate_queue_tasks(sources)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_id"], "build_kaikki_de_deu_core_a1")
        self.assertEqual(tasks[0]["status"], "PENDING")
        self.assertEqual(tasks[0]["source_lang"], "de")

if __name__ == '__main__':
    unittest.main()
