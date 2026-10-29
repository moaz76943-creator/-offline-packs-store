#!/usr/bin/env python3
import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tools.merge_coordinator.protection_gate import verify_required_gate_check

class TestStrictCheckGate(unittest.TestCase):
    def test_empty_checks_fails(self):
        passed, reason = verify_required_gate_check([])
        self.assertFalse(passed)
        self.assertIn("ABSENT", reason)

    def test_missing_required_check_fails(self):
        checks = [{"name": "some-other-check", "status": "completed", "conclusion": "success"}]
        passed, reason = verify_required_gate_check(checks)
        self.assertFalse(passed)
        self.assertIn("MISSING", reason)

    def test_skipped_required_check_fails(self):
        checks = [{"name": "public-pr-merge-gate", "status": "completed", "conclusion": "skipped"}]
        passed, reason = verify_required_gate_check(checks)
        self.assertFalse(passed)
        self.assertIn("NON_SUCCESS", reason)

    def test_success_required_check_passes(self):
        checks = [{"name": "public-pr-merge-gate", "status": "completed", "conclusion": "success"}]
        passed, reason = verify_required_gate_check(checks)
        self.assertTrue(passed)
        self.assertEqual(reason, "REQUIRED_CHECK_PASSED")

if __name__ == "__main__":
    unittest.main()
