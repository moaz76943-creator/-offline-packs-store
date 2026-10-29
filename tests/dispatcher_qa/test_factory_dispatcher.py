import json
import os
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.dispatcher.factory_dispatcher import dispatch_queued_tasks

class TestFactoryDispatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.queue_path = os.path.join(self.temp_dir.name, "queue.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dispatches_queued_tasks_and_updates_status(self):
        initial_data = {
            "tasks": [
                {"task_id": "task_1", "status": "QUEUED", "source_id": "kaikki_de"},
                {"task_id": "task_2", "status": "DISPATCHED", "source_id": "old_source"}
            ]
        }
        with open(self.queue_path, 'w') as f:
            json.dump(initial_data, f)

        ok, msg, dispatched = dispatch_queued_tasks(self.queue_path, max_batch=5)
        self.assertTrue(ok)
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]['task_id'], "task_1")
        self.assertEqual(dispatched[0]['status'], "DISPATCHED")
        self.assertIn("dispatched_at", dispatched[0])

        # Verify file persisted with updated status
        with open(self.queue_path, 'r') as f:
            updated = json.load(f)
        t1 = [t for t in updated['tasks'] if t['task_id'] == 'task_1'][0]
        self.assertEqual(t1['status'], "DISPATCHED")

    def test_handles_empty_queue_without_exception(self):
        with open(self.queue_path, 'w') as f:
            json.dump({"tasks": []}, f)

        ok, msg, dispatched = dispatch_queued_tasks(self.queue_path)
        self.assertTrue(ok)
        self.assertEqual(len(dispatched), 0)

if __name__ == "__main__":
    unittest.main()
