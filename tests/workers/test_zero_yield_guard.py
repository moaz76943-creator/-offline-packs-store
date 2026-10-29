import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.workers.zero_yield_guard import verify_non_zero_yield, ZeroYieldError

class TestZeroYieldGuard(unittest.TestCase):
    def test_valid_list_and_dict(self):
        self.assertEqual(verify_non_zero_yield(["apple", "banana"]), 2)
        self.assertEqual(verify_non_zero_yield({"de": "Wasser"}), 1)

    def test_empty_collection_raises(self):
        with self.assertRaises(ZeroYieldError):
            verify_non_zero_yield([])

    def test_zero_byte_file_raises(self):
        with tempfile.NamedTemporaryFile() as tmp:
            with self.assertRaises(ZeroYieldError):
                verify_non_zero_yield(tmp.name)

if __name__ == '__main__':
    unittest.main()
