import os
import unittest
import zlib
import json
import tempfile
import shutil
from unittest.mock import patch
from tools.media_optimizer.compiler import MediaPackCompiler, TokenValidationError

class TestMediaPackCompiler(unittest.TestCase):
    def setUp(self):
        self.compiler = MediaPackCompiler()
        self.output_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def _create_mock_vct(self, concept_id, paths, version=1, license='CC0', padding='', source_hash='dummy_hash'):
        data = {
            'concept_id': concept_id,
            'version': version,
            'license': license,
            'paths': paths,
            'source_hash': source_hash
        }
        if padding:
            data['padding'] = padding
        j = json.dumps(data, separators=(',', ':'))
        return zlib.compress(j.encode('utf-8'))

    def test_valid_token(self):
        token = self._create_mock_vct('concept.house', ['M0 0 L10 10'])
        pack = self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)
        self.assertIn('concept.house', pack['concepts'])
        self.assertEqual(len(pack['geometries']), 1)

    def test_exceeds_2048_bytes(self):
        # Create a large payload that exceeds 2048 bytes after compression
        # Use random or difficult to compress data
        import random, string
        padding = ''.join(random.choices(string.ascii_letters, k=4000))
        token = self._create_mock_vct('concept.huge', ['M0 0 L10 10'], padding=padding)
        with self.assertRaises(TokenValidationError) as ctx:
            self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)
        self.assertIn("exceeds 2048 bytes", str(ctx.exception))

    def test_exceeds_50_paths(self):
        paths = ['M0 0 L10 10'] * 51
        token = self._create_mock_vct('concept.many_paths', paths)
        with self.assertRaises(TokenValidationError) as ctx:
            self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)
        self.assertIn("exceeds 50 paths", str(ctx.exception))

    def test_invalid_license(self):
        token = self._create_mock_vct('concept.house', ['M0 0 L10 10'], license='GPL')
        with self.assertRaises(TokenValidationError) as ctx:
            self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)
        self.assertIn("Unsupported license", str(ctx.exception))

    def test_invalid_zlib(self):
        token = b'not zlib data'
        with self.assertRaises(TokenValidationError) as ctx:
            self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)
        self.assertIn("Invalid zlib compression", str(ctx.exception))

    def test_invalid_json(self):
        token = zlib.compress(b'{invalid_json')
        with self.assertRaises(TokenValidationError) as ctx:
            self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)
        self.assertIn("Invalid JSON metadata", str(ctx.exception))

    def test_missing_source_hash(self):
        data = {
            'concept_id': 'concept.house',
            'version': 1,
            'license': 'CC0',
            'paths': ['M0 0 L10 10']
        }
        token = zlib.compress(json.dumps(data).encode('utf-8'))
        with self.assertRaises(TokenValidationError) as ctx:
            self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)
        self.assertIn("Missing source_hash", str(ctx.exception))

    def test_geometry_deduplication(self):
        token1 = self._create_mock_vct('concept.house', ['M0 0 L10 10'])
        token2 = self._create_mock_vct('concept.dwelling', ['M0 0 L10 10'])
        pack = self.compiler.compile_pack([token1, token2], {}, self.output_dir, downstream_evidence=True)

        self.assertEqual(len(pack['concepts']), 2)
        self.assertEqual(len(pack['geometries']), 1)

        hash1 = pack['concepts']['concept.house']['geometry_hash']
        hash2 = pack['concepts']['concept.dwelling']['geometry_hash']
        self.assertEqual(hash1, hash2)

    def test_package_metadata(self):
        token = self._create_mock_vct('concept.house', ['M0 0 L10 10'])
        pack = self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)
        self.assertIn('package_metadata', pack)
        self.assertIn('sha256', pack['package_metadata'])
        self.assertIn('size_bytes', pack['package_metadata'])

    def test_incremental_updates(self):
        token1 = self._create_mock_vct('concept.house', ['M0 0 L10 10'])
        pack1 = self.compiler.compile_pack([token1], {}, self.output_dir, downstream_evidence=True)

        # Now change the concept's version
        token2 = self._create_mock_vct('concept.house', ['M0 0 L10 10'], version=2)

        # New compiler compilation with prior index
        out2 = tempfile.mkdtemp()
        try:
            self.compiler.compile_pack([token2], pack1, out2, downstream_evidence=True)

            with open(os.path.join(out2, 'events.json'), 'r') as f:
                events = json.load(f)

            self.assertIn('concept.house', events['updated'])
            self.assertNotIn('concept.house', events['unchanged'])
        finally:
            shutil.rmtree(out2, ignore_errors=True)

    def test_atomic_rollback(self):
        token = self._create_mock_vct('concept.house', ['M0 0 L10 10'])

        # Create a mock file in output dir to simulate existing state
        os.makedirs(self.output_dir, exist_ok=True)
        mock_file = os.path.join(self.output_dir, 'keep_me.txt')
        with open(mock_file, 'w') as f:
            f.write('keep')

        with patch('os.rename', side_effect=Exception('Simulated Failure')):
            with self.assertRaises(Exception):
                self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=True)

        # Existing output_dir should not be modified on failure
        self.assertTrue(os.path.exists(mock_file))

    def test_downstream_evidence_required(self):
        token = self._create_mock_vct('concept.house', ['M0 0 L10 10'])
        with self.assertRaises(ValueError) as ctx:
            self.compiler.compile_pack([token], {}, self.output_dir, downstream_evidence=False)
        self.assertIn("WordBit decoder compatibility evidence is required", str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
