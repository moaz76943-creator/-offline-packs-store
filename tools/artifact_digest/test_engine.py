import unittest
import os
import tempfile
import json
import shutil
from pathlib import Path
from tools.artifact_digest.engine import (
    compute_sha256,
    secure_resolve_path,
    validate_artifact,
    build_digest_index,
    compare_indexes
)

class TestDigestEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_content_identity_validation(self):
        base_dir = os.path.join(self.test_dir, "base_identity")
        os.makedirs(base_dir)

        file1 = "ident.txt"
        with open(os.path.join(base_dir, file1), 'w') as f:
            f.write("content identity")

        real_hash = compute_sha256(os.path.join(base_dir, file1))

        records = [
            {'path': file1, 'source_id': 's1', 'license_id': 'l1', 'asset_id': 'a1', 'version': 'v1', 'size_bytes': 16, 'sha256': 'wrong_hash'}
        ]

        out_path = os.path.join(self.test_dir, "identity_index.json")
        build_digest_index(base_dir, records, out_path)

        self.assertTrue(os.path.exists(out_path))
        with open(out_path, 'r') as f:
            index = json.load(f)

        self.assertIn(file1, index)
        self.assertTrue(index[file1].get('invalid'))
        self.assertIn("Hash mismatch", index[file1].get('error'))

    def test_tampered_bytes(self):
        file1 = os.path.join(self.test_dir, "file1.txt")
        file2 = os.path.join(self.test_dir, "file2.txt")
        with open(file1, 'w') as f: f.write("hello world")
        with open(file2, 'w') as f: f.write("hello_world")

        hash1 = compute_sha256(file1)
        hash2 = compute_sha256(file2)
        self.assertNotEqual(hash1, hash2)

    def test_deterministic_hashing(self):
        file1 = os.path.join(self.test_dir, "file1.txt")
        with open(file1, 'w') as f: f.write("consistent content")

        hash1 = compute_sha256(file1)
        hash2 = compute_sha256(file1)
        self.assertEqual(hash1, hash2)

    def test_malicious_path_traversals(self):
        base_dir = os.path.join(self.test_dir, "base")
        os.makedirs(base_dir)

        # Valid path
        valid_path = "valid.txt"
        with open(os.path.join(base_dir, valid_path), 'w') as f: f.write("valid")
        resolved = secure_resolve_path(base_dir, valid_path)
        self.assertTrue(str(resolved).startswith(str(Path(base_dir).resolve())))

        # Malicious path
        malicious_path = "../escaped.txt"
        with self.assertRaises(ValueError):
            secure_resolve_path(base_dir, malicious_path)

        # Absolute path escape
        absolute_escape = "/etc/passwd"
        with self.assertRaises(ValueError):
            secure_resolve_path(base_dir, absolute_escape)

    def test_declared_size_validation(self):
        filepath = os.path.join(self.test_dir, "size_test.txt")
        with open(filepath, 'w') as f: f.write("12345") # 5 bytes

        valid_meta = {
            'source_id': 's1', 'license_id': 'l1', 'asset_id': 'a1', 'version': 'v1',
            'size_bytes': 5
        }
        self.assertTrue(validate_artifact(filepath, valid_meta))

        invalid_meta = valid_meta.copy()
        invalid_meta['size_bytes'] = 6
        with self.assertRaises(ValueError) as ctx:
            validate_artifact(filepath, invalid_meta)
        self.assertIn("Size mismatch", str(ctx.exception))

    def test_missing_files(self):
        filepath = os.path.join(self.test_dir, "missing.txt")
        meta = {'source_id': 's1', 'license_id': 'l1', 'asset_id': 'a1', 'version': 'v1'}

        with self.assertRaises(FileNotFoundError):
            validate_artifact(filepath, meta)

    def test_valid_provenance(self):
        filepath = os.path.join(self.test_dir, "prov.txt")
        with open(filepath, 'w') as f: f.write("prov")

        # Missing source_id
        meta1 = {'license_id': 'l1', 'asset_id': 'a1', 'version': 'v1'}
        with self.assertRaises(ValueError) as ctx:
            validate_artifact(filepath, meta1)
        self.assertIn("Invalid provenance", str(ctx.exception))

        # Empty license_id
        meta2 = {'source_id': 's1', 'license_id': '', 'asset_id': 'a1', 'version': 'v1'}
        with self.assertRaises(ValueError):
            validate_artifact(filepath, meta2)

    def test_build_digest_index_and_atomic_save(self):
        base_dir = os.path.join(self.test_dir, "base")
        os.makedirs(base_dir)

        file1 = "f1.txt"
        with open(os.path.join(base_dir, file1), 'w') as f: f.write("content 1")

        file2 = "f2.txt"
        with open(os.path.join(base_dir, file2), 'w') as f: f.write("content 2")

        records = [
            {'path': file1, 'source_id': 's1', 'license_id': 'l1', 'asset_id': 'a1', 'version': 'v1', 'size_bytes': 9},
            {'path': file2, 'source_id': 's2', 'license_id': 'l2', 'asset_id': 'a2', 'version': 'v2', 'size_bytes': 9}
        ]

        out_path = os.path.join(self.test_dir, "index.json")
        build_digest_index(base_dir, records, out_path)

        self.assertTrue(os.path.exists(out_path))
        with open(out_path, 'r') as f:
            index = json.load(f)

        self.assertIn(file1, index)
        self.assertIn(file2, index)
        self.assertEqual(index[file1]['size_bytes'], 9)
        self.assertEqual(index[file1]['source_id'], 's1')

    def test_incremental_updates(self):
        old_index = {
            "unchanged.txt": {"sha256": "hash1", "source_id": "s1", "license_id": "l1", "asset_id": "a1", "version": "v1"},
            "updated_hash.txt": {"sha256": "hash2", "source_id": "s2", "license_id": "l2", "asset_id": "a2", "version": "v2"},
            "updated_meta.txt": {"sha256": "hash3", "source_id": "s3", "license_id": "l3", "asset_id": "a3", "version": "v1"},
            "deleted.txt": {"sha256": "hash4", "source_id": "s4", "license_id": "l4", "asset_id": "a4", "version": "v1"},
        }

        new_index = {
            "unchanged.txt": {"sha256": "hash1", "source_id": "s1", "license_id": "l1", "asset_id": "a1", "version": "v1"},
            "updated_hash.txt": {"sha256": "hash2_new", "source_id": "s2", "license_id": "l2", "asset_id": "a2", "version": "v2"},
            "updated_meta.txt": {"sha256": "hash3", "source_id": "s3", "license_id": "l3", "asset_id": "a3", "version": "v2"},
            "added.txt": {"sha256": "hash5", "source_id": "s5", "license_id": "l5", "asset_id": "a5", "version": "v1"},
        }

        events = compare_indexes(old_index, new_index)

        self.assertIn("unchanged.txt", events['unchanged'])
        self.assertIn("updated_hash.txt", events['updated'])
        self.assertIn("updated_meta.txt", events['updated'])
        self.assertIn("added.txt", events['updated'])
        self.assertIn("deleted.txt", events['deleted'])

    def test_bounded_memory(self):
        # We can't easily test that it truly uses bounded memory without memory profiler,
        # but we can verify it can hash a decently sized file correctly by reading in chunks.
        filepath = os.path.join(self.test_dir, "large.bin")
        chunk = b"A" * 65536
        with open(filepath, 'wb') as f:
            for _ in range(10): # ~650KB file
                f.write(chunk)

        hash_val = compute_sha256(filepath, chunk_size=1024)
        self.assertTrue(len(hash_val) == 64)

if __name__ == '__main__':
    unittest.main()
