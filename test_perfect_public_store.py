import os
import json
import gzip
import hashlib
import unittest
from perfect_public_store import create_minified_pack

class TestPerfectPublicStore(unittest.TestCase):
    def setUp(self):
        os.makedirs('packs', exist_ok=True)
        self.test_filename = 'test_minified.pack.gz'
        self.test_path = os.path.join('packs', self.test_filename)
        self.test_data = {
            "key1": "value 1",
            "key2": ["item1", "item2"],
            "key3": {"nested": "value"}
        }

    def tearDown(self):
        if os.path.exists(self.test_path):
            os.remove(self.test_path)

    def test_create_minified_pack(self):
        file_size, file_hash = create_minified_pack(self.test_filename, self.test_data)

        # Verify file exists
        self.assertTrue(os.path.exists(self.test_path))

        # Verify file size is correct
        self.assertEqual(file_size, os.path.getsize(self.test_path))

        # Verify hash is correct
        with open(self.test_path, 'rb') as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(file_hash, actual_hash)

        # Verify content can be decompressed and loaded as JSON
        with gzip.open(self.test_path, 'rt', encoding='utf-8') as f:
            content = f.read()
            # Ensure it is minified (no spaces after commas or colons)
            self.assertNotIn('": ', content)
            self.assertNotIn('", ', content)

            # Ensure it parses back to original data
            parsed_data = json.loads(content)
            self.assertEqual(self.test_data, parsed_data)

if __name__ == '__main__':
    unittest.main()
