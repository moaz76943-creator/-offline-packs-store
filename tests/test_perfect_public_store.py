import unittest
import os
import json
import gzip
import hashlib
import tempfile
import shutil
import ast
from pathlib import Path

# The legacy recipe executes pack/manifest/workflow generation on import.
# Load only its actual helper definition; exercise all file writes in setUp's
# scratch directory without running the unrelated recipe or publishing data.
recipe = Path(__file__).resolve().parents[1] / 'perfect_public_store.py'
definition = next(node for node in ast.parse(recipe.read_text(encoding='utf-8')).body
                  if isinstance(node, ast.FunctionDef) and node.name == 'create_minified_pack')
namespace = {'os': os, 'json': json, 'gzip': gzip, 'hashlib': hashlib}
exec(compile(ast.Module(body=[definition], type_ignores=[]), str(recipe), 'exec'), namespace)
create_minified_pack = namespace['create_minified_pack']

class TestPerfectPublicStore(unittest.TestCase):
    def setUp(self):
        # We need a packs directory for the function to work correctly,
        # but we shouldn't pollute the real 'packs' dir. However, the function
        # hardcodes os.path.join('packs', filename).
        # We can either mock os.path.join or run in a temporary directory.
        self.original_cwd = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        os.chdir(self.test_dir)
        os.makedirs('packs', exist_ok=True)

        self.test_filename = 'test_data.pack.gz'
        self.test_data = {
            "type": "vocabulary",
            "items": [
                {"word": "Apfel", "image": "apple.webp"},
                {"word": "Baum", "image": "tree.webp"}
            ]
        }

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_create_minified_pack(self):
        size, file_hash = create_minified_pack(self.test_filename, self.test_data)

        path = os.path.join('packs', self.test_filename)
        self.assertTrue(os.path.exists(path), "File should be created in the packs directory")

        actual_size = os.path.getsize(path)
        self.assertEqual(size, actual_size, "Returned size should match actual file size")

        with open(path, 'rb') as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(file_hash, actual_hash, "Returned hash should match actual file hash")

        # Verify gzip content
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            content = f.read()

        # Verify minification (no spaces after colons or commas)
        self.assertNotIn(": ", content, "Content should be minified without spaces after colons")
        self.assertNotIn(", ", content, "Content should be minified without spaces after commas")
        self.assertNotIn("\n", content, "Content should be minified without newlines")

        # Verify valid JSON and correct data
        decoded_data = json.loads(content)
        self.assertEqual(self.test_data, decoded_data, "Decoded JSON should match original data")

if __name__ == '__main__':
    unittest.main()
