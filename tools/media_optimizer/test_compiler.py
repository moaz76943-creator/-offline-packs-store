import unittest
import os
import tempfile
import json
import zlib
from tools.media_optimizer.compiler import (
    validate_token, MAX_TOKEN_SIZE, MAX_PATHS, MediaPackCompiler
)

class TestTokenValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def create_token(self, filename, data, compress=True):
        filepath = os.path.join(self.temp_dir.name, filename)
        content = json.dumps(data).encode('utf-8')
        if compress:
            content = zlib.compress(content)
        with open(filepath, 'wb') as f:
            f.write(content)
        return filepath

    def get_valid_token_data(self):
        return {
            "license_id": "CC0-1.0",
            "concept_id": "concept_1",
            "version": "1.0",
            "source_hash": "abc123hash",
            "geometry": {
                "encoding_version": 1,
                "paths": [{"d": "M0 0 L10 10"}]
            }
        }

    def test_valid_token(self):
        data = self.get_valid_token_data()
        path = self.create_token('valid.vct', data)
        token_hash, geom_hash, b64_str, parsed = validate_token(path)
        self.assertEqual(parsed['concept_id'], 'concept_1')
        self.assertTrue(len(token_hash) == 64)
        self.assertTrue(len(geom_hash) == 64)

    def test_invalid_license(self):
        data = self.get_valid_token_data()
        data['license_id'] = 'MIT'
        path = self.create_token('invalid_lic.vct', data)
        with self.assertRaisesRegex(ValueError, "Invalid license"):
            validate_token(path)

    def test_corrupt_token_not_zlib(self):
        path = self.create_token('not_zlib.vct', {"a": 1}, compress=False)
        with self.assertRaisesRegex(ValueError, "not valid zlib compressed data"):
            validate_token(path)

    def test_oversized_token(self):
        data = self.get_valid_token_data()
        data['geometry']['paths'] = [{"d": "M0 0 L10 10 " * 50}] * 10
        path = self.create_token('oversized.vct', data)
        with open(path, 'ab') as f:
            f.write(b'0' * (MAX_TOKEN_SIZE + 100))
        with self.assertRaisesRegex(ValueError, f"exceeds {MAX_TOKEN_SIZE} bytes"):
            validate_token(path)

    def test_exceeds_max_paths(self):
        data = self.get_valid_token_data()
        data['geometry']['paths'] = [{"d": "M0 0 L10 10"}] * (MAX_PATHS + 1)
        path = self.create_token('max_paths.vct', data)
        with self.assertRaisesRegex(ValueError, "exceeds bounded memory limit"):
            validate_token(path)

    def test_missing_provenance(self):
        data = self.get_valid_token_data()
        del data['source_hash']
        path = self.create_token('no_prov.vct', data)
        with self.assertRaisesRegex(ValueError, "Missing required provenance fields"):
            validate_token(path)

    def test_malformed_geometry(self):
        data = self.get_valid_token_data()
        data['geometry']['paths'] = [{"bad": "data"}]
        path = self.create_token('bad_geom.vct', data)
        with self.assertRaisesRegex(ValueError, "missing path data"):
            validate_token(path)


class TestMediaPackCompiler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def create_token(self, filename, data, compress=True):
        filepath = os.path.join(self.temp_dir.name, filename)
        content = json.dumps(data).encode('utf-8')
        if compress:
            content = zlib.compress(content)
        with open(filepath, 'wb') as f:
            f.write(content)
        return filepath

    def get_valid_token_data(self, concept_id="c1", version="1", source_hash="hash1", geom_d="M0 0"):
        return {
            "license_id": "CC0-1.0",
            "concept_id": concept_id,
            "version": version,
            "source_hash": source_hash,
            "geometry": {
                "encoding_version": 1,
                "paths": [{"d": geom_d}]
            }
        }

    def test_geometry_deduplication(self):
        compiler = MediaPackCompiler()

        data1 = self.get_valid_token_data("c1", "1", "hash1", "M0 0")
        path1 = self.create_token('c1.vct', data1)

        data2 = self.get_valid_token_data("c2", "1", "hash2", "M0 0")
        path2 = self.create_token('c2.vct', data2)

        compiler.add_token(path1, {"concept_id": "c1", "version": "1", "source_hash": "hash1"})
        compiler.add_token(path2, {"concept_id": "c2", "version": "1", "source_hash": "hash2"})

        # 2 concepts, 1 geometry
        self.assertEqual(len(compiler.concepts), 2)
        self.assertEqual(len(compiler.geometries), 1)

    def test_incremental_reuse(self):
        prior_pack = {
            "c1": {
                "version": "1",
                "source_hash": "hash1",
                "token_hash": "faketokenhash",
                "geometry_hash": "fakegeomhash",
                "base64_data": "fakedata",
                "label": "test label"
            }
        }
        compiler = MediaPackCompiler(prior_pack_index=prior_pack)
        compiler.add_token("does_not_exist.vct", {"concept_id": "c1", "version": "1", "source_hash": "hash1"})

        self.assertEqual(compiler.stats['reused'], 1)
        self.assertEqual(compiler.stats['added'], 0)
        self.assertIn('fakegeomhash', compiler.geometries)

    def test_atomic_rollback(self):
        compiler = MediaPackCompiler()
        target_dir = os.path.join(self.temp_dir.name, "output_pack")
        os.makedirs(target_dir)
        with open(os.path.join(target_dir, "pack.json"), "w") as f:
            f.write("old data")

        import unittest.mock as mock
        with mock.patch('os.replace', side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                compiler.build_pack(target_dir, decoder_evidence_provided=True)

        with open(os.path.join(target_dir, "pack.json"), "r") as f:
            self.assertEqual(f.read(), "old data")

    def test_determinism(self):
        data = self.get_valid_token_data("c1", "1", "h1")
        path = self.create_token('c1.vct', data)

        out1 = os.path.join(self.temp_dir.name, "out1")
        comp1 = MediaPackCompiler()
        comp1.add_token(path, {"concept_id": "c1", "version": "1", "source_hash": "h1"})
        comp1.build_pack(out1, decoder_evidence_provided=True)

        out2 = os.path.join(self.temp_dir.name, "out2")
        comp2 = MediaPackCompiler()
        comp2.add_token(path, {"concept_id": "c1", "version": "1", "source_hash": "h1"})
        comp2.build_pack(out2, decoder_evidence_provided=True)

        with open(os.path.join(out1, "metadata.json")) as f:
            meta1 = json.load(f)
        with open(os.path.join(out2, "metadata.json")) as f:
            meta2 = json.load(f)

        self.assertEqual(meta1['sha256'], meta2['sha256'])

    def test_decoder_evidence(self):
        compiler = MediaPackCompiler()
        data = self.get_valid_token_data("c1", "1", "h1")
        path = self.create_token('c1.vct', data)
        compiler.add_token(path, {"concept_id": "c1", "version": "1", "source_hash": "h1"})

        out = os.path.join(self.temp_dir.name, "out")

        compiler.build_pack(out, decoder_evidence_provided=False)
        with open(os.path.join(out, "metadata.json")) as f:
            meta = json.load(f)
        self.assertFalse(meta['production_ready'])
        with open(os.path.join(out, "wordbit_compatibility.json")) as f:
            wb = json.load(f)
        self.assertFalse(wb['decoder_compatible'])

        compiler.build_pack(out, decoder_evidence_provided=True)
        with open(os.path.join(out, "metadata.json")) as f:
            meta = json.load(f)
        self.assertTrue(meta['production_ready'])
        with open(os.path.join(out, "wordbit_compatibility.json")) as f:
            wb = json.load(f)
        self.assertTrue(wb['decoder_compatible'])

if __name__ == '__main__':
    unittest.main()
