import unittest
from tools.compile_store_packs import digest

class TestCompileStorePacks(unittest.TestCase):
    def test_digest(self):
        # Test empty byte string
        self.assertEqual(
            digest(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        # Test a simple string
        self.assertEqual(
            digest(b"hello world"),
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        )
        # Test a string with non-ascii characters (must be encoded to bytes)
        self.assertEqual(
            digest("café".encode("utf-8")),
            "850f7dc43910ff890f8879c0ed26fe697c93a067ad93a7d50f466a7028a9bf4e"
        )

if __name__ == '__main__':
    unittest.main()
