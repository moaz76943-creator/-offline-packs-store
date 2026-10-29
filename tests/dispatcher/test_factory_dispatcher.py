import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.dispatcher.factory_dispatcher import dispatch_next_task, complete_task

class TestFactoryDispatcher(unittest.TestCase):
    def test_dispatch_and_complete_cycle(self):
        tasks = [
            {"task_id": "task_1", "status": "PENDING"},
            {"task_id": "task_2", "status": "PENDING"},
        ]
        
        dispatched = dispatch_next_task(tasks)
        self.assertIsNotNone(dispatched)
        self.assertEqual(dispatched["task_id"], "task_1")
        self.assertEqual(dispatched["status"], "IN_PROGRESS")
        self.assertIn("dispatched_at", dispatched)

        # المهمة التالية يجب أن تكون task_2
        next_dispatched = dispatch_next_task(tasks)
        self.assertIsNotNone(next_dispatched)
        self.assertEqual(next_dispatched["task_id"], "task_2")

        # إنهاء المهمة
        self.assertTrue(complete_task(tasks, "task_1", success=True))
        self.assertEqual(tasks[0]["status"], "COMPLETED")
        self.assertIn("completed_at", tasks[0])

if __name__ == '__main__':
    unittest.main()
