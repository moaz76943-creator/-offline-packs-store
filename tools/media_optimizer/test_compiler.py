import unittest
import os
import json
import zlib
import shutil
import tempfile
from unittest.mock import patch
from tools.media_optimizer.compiler import MediaPackCompiler, ValidationError

class TestMediaPackCompiler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.temp_dir, "output")
        self.compiler = MediaPackCompiler(decoder_evidence_provided=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _create_token(self, filename, data, uncompressed=False, override_size=None):
        path = os.path.join(self.temp_dir, filename)
        json_str = json.dumps(data)
        if uncompressed:
            content = json_str.encode('utf-8')
        else:
            content = zlib.compress(json_str.encode('utf-8'))

        with open(path, 'wb') as f:
            if override_size:
                f.write(b'0' * override_size)
            else:
                f.write(content)
        return path

    def test_valid_integration_and_deduplication(self):
        t1 = self._create_token("t1.vct", {
            "id": "concept_1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]
        })
        t2 = self._create_token("t2.vct", {
            "id": "concept_2", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]
        })
        t3 = self._create_token("t3.vct", {
            "id": "concept_3", "version": 1, "license": "PUBLIC-DOMAIN", "paths": ["M20 20"]
        })

        meta = self.compiler.build_pack([t1, t2, t3], self.output_dir)

        pack_path = os.path.join(self.output_dir, "pack.json")
        self.assertTrue(os.path.exists(pack_path))
        with open(pack_path, 'r') as f:
            pack_data = json.load(f)

        # Deduplication check: two identical geometries should result in only 2 items in geometry pool
        self.assertEqual(len(pack_data["geometry_pool"]), 2)

        # Check concepts
        self.assertEqual(len(pack_data["concepts"]), 3)
        self.assertEqual(pack_data["concepts"]["concept_1"]["geom_id"], pack_data["concepts"]["concept_2"]["geom_id"])
        self.assertNotEqual(pack_data["concepts"]["concept_1"]["geom_id"], pack_data["concepts"]["concept_3"]["geom_id"])

        self.assertEqual(len(meta["delta_plan"]["added"]), 3)

    def test_oversized_token(self):
        t1 = self._create_token("t1.vct", {
            "id": "concept_1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]
        }, override_size=2048)

        with self.assertRaisesRegex(ValidationError, "exceeds 2048 bytes"):
            self.compiler.build_pack([t1], self.output_dir)

    def test_invalid_license(self):
        t1 = self._create_token("t1.vct", {
            "id": "concept_1", "version": 1, "license": "CC-BY", "paths": ["M10 10"]
        })

        with self.assertRaisesRegex(ValidationError, "Unsupported or missing license"):
            self.compiler.build_pack([t1], self.output_dir)

    def test_corrupt_zlib_token(self):
        t1 = self._create_token("t1.vct", {
            "id": "concept_1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]
        }, uncompressed=True) # Will fail zlib decompression

        with self.assertRaisesRegex(ValidationError, "Invalid zlib stream"):
            self.compiler.build_pack([t1], self.output_dir)

    def test_incremental_updates(self):
        t1 = self._create_token("t1.vct", {"id": "c1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]})
        self.compiler.build_pack([t1], self.output_dir)

        # Update c1, add c2
        t1_updated = self._create_token("t1.vct", {"id": "c1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10 L20"]})
        t2 = self._create_token("t2.vct", {"id": "c2", "version": 1, "license": "CC0-1.0", "paths": ["M20 20"]})

        prev_pack_path = os.path.join(self.output_dir, "pack.json")
        meta = self.compiler.build_pack([t1_updated, t2], self.output_dir, previous_pack_path=prev_pack_path)

        self.assertIn("c2", meta["delta_plan"]["added"])
        self.assertIn("c1", meta["delta_plan"]["updated"])
        self.assertEqual(len(meta["delta_plan"]["removed"]), 0)

        # Remove c1
        meta2 = self.compiler.build_pack([t2], self.output_dir, previous_pack_path=prev_pack_path)
        self.assertIn("c1", meta2["delta_plan"]["removed"])

    @patch('shutil.move')
    def test_atomic_rollback(self, mock_move):
        mock_move.side_effect = OSError("Simulated failure")
        t1 = self._create_token("t1.vct", {"id": "c1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]})

        with self.assertRaises(OSError):
            self.compiler.build_pack([t1], self.output_dir)

        self.assertFalse(os.path.exists(os.path.join(self.output_dir, "pack.json")))
        self.assertFalse(os.path.exists(os.path.join(self.output_dir, "pack.json.tmp")))

    def test_decoder_evidence_enforcement(self):
        compiler_no_evidence = MediaPackCompiler(decoder_evidence_provided=False)
        t1 = self._create_token("t1.vct", {"id": "c1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]})

        with self.assertRaisesRegex(ValidationError, "Cannot build production-ready pack"):
            compiler_no_evidence.build_pack([t1], self.output_dir)

    def test_deterministic_output(self):
        t1_a = self._create_token("t1_a.vct", {"id": "c1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]})
        t2_a = self._create_token("t2_a.vct", {"id": "c2", "version": 1, "license": "CC0-1.0", "paths": ["M20 20"]})

        meta_a = self.compiler.build_pack([t1_a, t2_a], os.path.join(self.temp_dir, "out_a"))

        t1_b = self._create_token("t1_b.vct", {"id": "c1", "version": 1, "license": "CC0-1.0", "paths": ["M10 10"]})
        t2_b = self._create_token("t2_b.vct", {"id": "c2", "version": 1, "license": "CC0-1.0", "paths": ["M20 20"]})

        # Even if built in different order
        meta_b = self.compiler.build_pack([t2_b, t1_b], os.path.join(self.temp_dir, "out_b"))

        self.assertEqual(meta_a["sha256"], meta_b["sha256"])

if __name__ == '__main__':
    unittest.main()
