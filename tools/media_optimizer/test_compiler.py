import unittest
import os
import json
import zlib
import tempfile
from tools.media_optimizer.token import CompactVectorToken, TokenValidationError
from tools.media_optimizer.compiler import VectorPackCompiler
from tools.media_optimizer.storage import PackStorage, StorageError

class TestCompiler(unittest.TestCase):
    def setUp(self):
        self.valid_payload = {
            "concept_id": "test_concept",
            "version": 1,
            "source_hash": "abcd123",
            "license": "CC0-1.0",
            "paths": ["M10 10 H 90 V 90 H 10 L 10 10"]
        }
        self.valid_data = zlib.compress(json.dumps(self.valid_payload).encode('utf-8'))

    def test_token_validation_genuine(self):
        token = CompactVectorToken.from_bytes(self.valid_data)
        self.assertEqual(token.concept_id, "test_concept")
        self.assertEqual(token.license, "CC0-1.0")

    def test_token_rejection_large(self):
        large_payload = self.valid_payload.copy()
        paths = []
        for i in range(500):
            paths.append(f"M{i} {i} H {i+10} V {i+10} Z")
        large_payload["paths"] = paths
        large_data = zlib.compress(json.dumps(large_payload).encode('utf-8'))

        with self.assertRaises(TokenValidationError):
            CompactVectorToken.from_bytes(large_data)

    def test_token_rejection_invalid_license(self):
        payload = self.valid_payload.copy()
        payload["license"] = "GPL-3.0"
        data = zlib.compress(json.dumps(payload).encode('utf-8'))
        with self.assertRaises(TokenValidationError):
            CompactVectorToken.from_bytes(data)

    def test_token_rejection_corrupt(self):
        corrupt_data = b"Not a valid zip or json format"
        with self.assertRaises(TokenValidationError):
            CompactVectorToken.from_bytes(corrupt_data)

    def test_token_rejection_malformed_json(self):
        data = zlib.compress(b'{"concept_id": "bad"')
        with self.assertRaises(TokenValidationError):
            CompactVectorToken.from_bytes(data)

    def test_token_rejection_unsupported_version(self):
        payload = self.valid_payload.copy()
        payload["version"] = 2
        data = zlib.compress(json.dumps(payload).encode('utf-8'))
        with self.assertRaises(TokenValidationError):
            CompactVectorToken.from_bytes(data)

    def test_geometry_deduplication(self):
        compiler = VectorPackCompiler()
        payload2 = self.valid_payload.copy()
        payload2["concept_id"] = "test_concept_2"
        data2 = zlib.compress(json.dumps(payload2).encode('utf-8'))

        compiler.build_pack([self.valid_data, data2])
        manifest = json.loads(compiler.compile().decode('utf-8'))

        self.assertEqual(len(manifest["concepts"]), 2)
        self.assertEqual(len(manifest["geometries"]), 1)

        gid1 = manifest["concepts"]["test_concept"]["geometry_id"]
        gid2 = manifest["concepts"]["test_concept_2"]["geometry_id"]
        self.assertEqual(gid1, gid2)

    def test_incremental_updates(self):
        compiler1 = VectorPackCompiler()
        compiler1.build_pack([self.valid_data])
        manifest1 = json.loads(compiler1.compile().decode('utf-8'))

        # Now incremental update
        compiler2 = VectorPackCompiler()
        compiler2.load_previous_pack(manifest1)

        # New concept
        payload2 = self.valid_payload.copy()
        payload2["concept_id"] = "test_concept_2"
        payload2["paths"] = ["M0 0"]
        data2 = zlib.compress(json.dumps(payload2).encode('utf-8'))

        compiler2.build_pack([self.valid_data, data2])
        manifest2 = json.loads(compiler2.compile().decode('utf-8'))

        self.assertEqual(len(manifest2["concepts"]), 2)
        self.assertEqual(len(manifest2["geometries"]), 2)

        self.assertEqual(
            manifest1["concepts"]["test_concept"]["geometry_id"],
            manifest2["concepts"]["test_concept"]["geometry_id"]
        )

    def test_atomic_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "pack.vp")
            storage = PackStorage(out_path)

            storage.stage_pack(b"dummy data")
            self.assertTrue(os.path.exists(storage.temp_path))

            # Make the output path invalid so commit fails
            storage.output_path = os.path.join(tmpdir, "nonexistent", "pack.vp")

            with self.assertRaises(StorageError):
                storage.commit()

            # Assert temp_path was cleaned up and is None
            self.assertIsNone(storage.temp_path)

    def test_determinism(self):
        compiler1 = VectorPackCompiler()
        compiler1.build_pack([self.valid_data])
        pack1 = compiler1.compile()

        compiler2 = VectorPackCompiler()
        compiler2.build_pack([self.valid_data])
        pack2 = compiler2.compile()

        self.assertEqual(pack1, pack2)

    def test_wordbit_compatibility(self):
        compiler = VectorPackCompiler()
        manifest = json.loads(compiler.compile().decode('utf-8'))
        self.assertIn("decoder_compatibility", manifest)
        self.assertEqual(manifest["decoder_compatibility"], "WordBit-Vector-v1")


if __name__ == '__main__':
    unittest.main()
