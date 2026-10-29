import unittest
import os
import gzip
import json
import hashlib

import perfect_public_store

class TestPerfectPublicStore(unittest.TestCase):
    def setUp(self):
        os.makedirs('packs', exist_ok=True)

    def test_create_minified_pack(self):
        test_filename = 'test_minified.pack.gz'
        test_data = {"key": "value", "list": [1, 2, 3], "nested": {"a": "b"}}

        path = os.path.join('packs', test_filename)
        if os.path.exists(path):
            os.remove(path)

        size, file_hash = perfect_public_store.create_minified_pack(test_filename, test_data)

        self.assertTrue(os.path.exists(path))
        self.assertEqual(size, os.path.getsize(path))

        with open(path, 'rb') as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(file_hash, actual_hash)

        with gzip.open(path, 'rt', encoding='utf-8') as f:
            content = f.read()

        expected_content = json.dumps(test_data, ensure_ascii=False, separators=(',', ':'))
        self.assertEqual(content, expected_content)

        # Verify minification logic on sample data by checking for absence of spaces
        self.assertNotIn(' ', content)

        if os.path.exists(path):
            os.remove(path)

if __name__ == '__main__':
    unittest.main()
