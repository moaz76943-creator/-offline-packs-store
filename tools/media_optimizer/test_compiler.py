import unittest
import zlib
import json
import os
import shutil
import tempfile
from unittest.mock import patch
from tools.media_optimizer.compiler import MediaCompiler, TokenValidationError, CompilationError, DiskSpaceError

class TestMediaCompiler(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.mkdtemp()
        self.compiler = MediaCompiler(self.output_dir)
        self.valid_token = {
            'concept_id': 'test-1',
            'version': 'v1',
            'paths': [{'d': 'M10 10'}],
            'source_evidence': {'license': 'CC0-1.0'},
            'source_hash': 'abc',
            'semantic_label': 'test icon'
        }
        self.valid_raw = zlib.compress(json.dumps(self.valid_token).encode())

    def tearDown(self):
        shutil.rmtree(self.output_dir)
        if os.path.exists(self.compiler.staging_dir):
            shutil.rmtree(self.compiler.staging_dir)

    def test_validate_valid_token(self):
        res = self.compiler.validate_token(self.valid_raw)
        self.assertEqual(res['concept_id'], 'test-1')

    def test_validate_size_limit(self):
        large_token = {'concept_id': 'large', 'paths': [{'d': 'M10'*1000}]}
        large_raw = zlib.compress(json.dumps(large_token).encode())
        self.compiler.max_bytes = 10 # Force fail
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(large_raw)

    def test_validate_corrupt_token(self):
        # Test non-zlib string
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(b"not_zlib_compressed")
        # Test invalid json
        invalid_json = zlib.compress(b"not json")
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(invalid_json)

    def test_validate_unsupported_encoding(self):
        tok = self.valid_token.copy()
        tok['version'] = 'v3'
        raw = zlib.compress(json.dumps(tok).encode())
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(raw)

    def test_validate_invalid_license(self):
        tok = self.valid_token.copy()
        tok['source_evidence'] = {'license': 'PROPRIETARY'}
        raw = zlib.compress(json.dumps(tok).encode())
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(raw)

    def test_deduplicate_geometry(self):
        t1 = self.valid_token.copy()
        t1['concept_id'] = 'c1'
        t2 = self.valid_token.copy()
        t2['concept_id'] = 'c2'

        geom_list, tokens = self.compiler.deduplicate_geometry([t1, t2])
        self.assertEqual(len(geom_list), 1)
        self.assertEqual(tokens[0]['geometry_ref'], 0)
        self.assertEqual(tokens[1]['geometry_ref'], 0)

    def test_compile_successful(self):
        runtime_evidence = {'compatible': True}
        res = self.compiler.compile([self.valid_raw], runtime_evidence=runtime_evidence)
        self.assertIn('sha256', res['metadata'])
        self.assertEqual(res['metadata']['concept_count'], 1)

    def test_compile_requires_evidence(self):
        with self.assertRaises(CompilationError):
            self.compiler.compile([self.valid_raw], runtime_evidence=None)

    def test_compile_delta_events(self):
        t1 = self.valid_token.copy()
        raw1 = zlib.compress(json.dumps(t1).encode())

        t2 = self.valid_token.copy()
        t2['concept_id'] = 'test-2'
        raw2 = zlib.compress(json.dumps(t2).encode())

        prior_pack_meta = {
            'concepts': {
                'test-1': {'source_hash': 'abc'}, # unchanged
                'test-old': {'source_hash': 'def'} # deleted
            }
        }

        res = self.compiler.compile([raw1, raw2], prior_pack_meta=prior_pack_meta, runtime_evidence={'compatible': True})
        events = {e['concept_id']: e['type'] for e in res['change_events']}

        self.assertEqual(events['test-1'], 'unchanged')
        self.assertEqual(events['test-2'], 'added')
        self.assertEqual(events['test-old'], 'deleted')

    def test_deterministic_output(self):
        t2 = self.valid_token.copy()
        t2['concept_id'] = 'test-2'
        raw2 = zlib.compress(json.dumps(t2).encode())

        # Order shouldn't matter
        res1 = self.compiler.compile([self.valid_raw, raw2], runtime_evidence={'compatible': True})
        res2 = self.compiler.compile([raw2, self.valid_raw], runtime_evidence={'compatible': True})

        self.assertEqual(res1['metadata']['sha256'], res2['metadata']['sha256'])

    @patch('shutil.disk_usage')
    def test_insufficient_disk_space(self, mock_disk):
        mock_disk.return_value = (1000, 1000, 0)
        with self.assertRaises(DiskSpaceError):
            self.compiler.compile([self.valid_raw], runtime_evidence={'compatible': True})

if __name__ == '__main__':
    unittest.main()
