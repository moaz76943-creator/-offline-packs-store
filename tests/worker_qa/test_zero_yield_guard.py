import json
import os
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.workers.zero_yield_guard import validate_worker_output

class TestZeroYieldGuard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_worker_with_valid_output_passes(self):
        filepath = os.path.join(self.temp_dir.name, "worker_out.json")
        with open(filepath, 'w') as f:
            json.dump({"entries": [{"word": "Hallo"}, {"word": "Buch"}]}, f)

        ok, msg = validate_worker_output(filepath, min_expected_entries=1)
        self.assertTrue(ok)
        self.assertIn("YIELD_VERIFIED: 2 valid entries", msg)

    def test_worker_with_zero_records_fails_closed(self):
        filepath = os.path.join(self.temp_dir.name, "empty_out.json")
        with open(filepath, 'w') as f:
            json.dump({"entries": []}, f)

        ok, msg = validate_worker_output(filepath, min_expected_entries=1)
        self.assertFalse(ok)
        self.assertIn("ZERO_YIELD_ERROR: Worker produced 0 entries", msg)

    def test_zero_byte_file_fails_closed(self):
        filepath = os.path.join(self.temp_dir.name, "zero_bytes.json")
        with open(filepath, 'w') as f:
            pass  # 0-byte file

        ok, msg = validate_worker_output(filepath, min_expected_entries=1)
        self.assertFalse(ok)
        self.assertIn("is zero bytes", msg)

if __name__ == "__main__":
    unittest.main()
