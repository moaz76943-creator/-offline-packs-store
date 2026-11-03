import copy
import unittest
import zlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
from tools.media_optimizer.compiler import MediaCompiler, TokenValidationError, CompilationError, DiskSpaceError
from legal.ledger.admission import SCHEMA, evaluate, sha256_file

class TestMediaCompiler(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.mkdtemp()
        self.repo = tempfile.mkdtemp()
        self.retrieval_sha = self._install_vector_source()
        self.compiler = MediaCompiler(self.output_dir, repo_root=self.repo)
        self.valid_token = {
            'concept_id': 'test-1',
            'version': 'v1',
            'paths': [{'d': 'M10 10'}],
            'source_evidence': {
                'source_id': 'fixture-vector',
                'dataset_version': '2026.10',
                'artifact_sha256': self.retrieval_sha,
            },
            'source_hash': 'abc',
            'semantic_label': 'test icon'
        }
        self.valid_raw = zlib.compress(json.dumps(self.valid_token).encode())

    def tearDown(self):
        shutil.rmtree(self.output_dir)
        shutil.rmtree(self.repo)
        if os.path.exists(self.compiler.staging_dir):
            shutil.rmtree(self.compiler.staging_dir)

    def _put(self, relative, content):
        path = Path(self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return relative

    def _install_vector_source(self):
        """Temp-dir gate fixture only. Nothing is written to the canonical ledger."""
        src = self._put('evidence/upstream.json', b'{"glyph":"fixture"}')
        lic = self._put('evidence/upstream-license.txt', b'Fixture publisher license snapshot')
        art = self._put('evidence/artwork.txt', b'Fixture vector artwork rights snapshot')
        source = {
            'source_id': 'fixture-vector', 'kind': 'vector_art',
            'origin_url': 'https://example.org/art', 'publisher': 'Fixture Publisher',
            'author': 'Fixture Author',
            'dataset_version': '2026.10',
            'retrieval': {
                'identity': 'fixture-snapshot-v1', 'url': 'https://example.org/art',
                'date': '2026-10-12', 'artifact_path': src,
                'sha256': sha256_file(Path(self.repo) / src),
            },
            'license': {
                'id': 'CC0-1.0',
                'evidence_url': 'https://example.org/art/license',
                'evidence_path': lic,
                'evidence_sha256': sha256_file(Path(self.repo) / lic),
                'artwork_evidence_url': 'https://example.org/art/artwork-license',
                'artwork_evidence_path': art,
                'artwork_evidence_sha256': sha256_file(Path(self.repo) / art),
            },
            'status': 'APPROVED_FOR_REDISTRIBUTION',
            'review': {'reviewer': 'fixture-reviewer', 'decision_url': 'https://example.org/review/1'},
            'alterations': ['no changes'],
        }
        self.source = source
        ledger = {'schema_version': SCHEMA, 'sources': [source]}
        self._put('legal/ledger/sources.json', json.dumps(ledger).encode())
        self.assertEqual([], evaluate(ledger, {'languages': [], 'packs': []}, [], self.repo))
        return source['retrieval']['sha256']

    def _rewrite_source(self, **changes):
        source = copy.deepcopy(self.source)
        source.update(changes)
        ledger = {'schema_version': SCHEMA, 'sources': [source]}
        self._put('legal/ledger/sources.json', json.dumps(ledger).encode())
        return source

    def _raw(self, token):
        return zlib.compress(json.dumps(token).encode())

    def test_validate_valid_token(self):
        res = self.compiler.validate_token(self.valid_raw)
        self.assertEqual(res['concept_id'], 'test-1')

    def test_license_label_is_not_provenance(self):
        for label in ('CC0', 'CC-BY', 'CC0-1.0', 'PUBLIC-DOMAIN', 'GFDL-1.3-only', 'CC-BY-SA-4.0'):
            tok = copy.deepcopy(self.valid_token)
            tok['source_evidence'] = {'license': label}
            raw = self._raw(tok)
            with self.assertRaises(TokenValidationError):
                self.compiler.validate_token(raw)
            with self.assertRaises(CompilationError):
                self.compiler.compile([raw], runtime_evidence={'compatible': True})
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, 'pack.vct')))

    def test_production_ledger_rejects_license_label(self):
        output = tempfile.mkdtemp()
        compiler = MediaCompiler(output)
        self.addCleanup(lambda: shutil.rmtree(output, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(compiler.staging_dir, ignore_errors=True))
        tok = copy.deepcopy(self.valid_token)
        tok['source_evidence'] = {'license': 'CC0'}
        with self.assertRaises(TokenValidationError):
            compiler.validate_token(self._raw(tok))

    def test_caller_license_cannot_override_ledger(self):
        tok = copy.deepcopy(self.valid_token)
        tok['source_evidence']['license'] = 'CC0'
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(self._raw(tok))

    def test_missing_vector_art_proof_fails_closed(self):
        source = copy.deepcopy(self.source)
        for key in ('artwork_evidence_url', 'artwork_evidence_path', 'artwork_evidence_sha256'):
            del source['license'][key]
        self._put('legal/ledger/sources.json', json.dumps({'schema_version': SCHEMA, 'sources': [source]}).encode())
        with self.assertRaises(TokenValidationError) as caught:
            self.compiler.validate_token(self.valid_raw)
        self.assertIn('ARTWORK_LICENSE', str(caught.exception))

    def test_missing_source_author_fails_closed(self):
        source = copy.deepcopy(self.source)
        source.pop('author', None)
        self._put(
            'legal/ledger/sources.json',
            json.dumps({'schema_version': SCHEMA, 'sources': [source]}).encode(),
        )
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(self.valid_raw)

    def test_unapproved_source_fails_closed(self):
        self._rewrite_source(status='REVIEW_REQUIRED')
        with self.assertRaises(TokenValidationError) as caught:
            self.compiler.validate_token(self.valid_raw)
        self.assertIn('REVIEW_REQUIRED', str(caught.exception))

    def test_non_vector_source_is_not_artwork_proof(self):
        source = copy.deepcopy(self.source)
        source['kind'] = 'dictionary'
        for key in ('artwork_evidence_url', 'artwork_evidence_path', 'artwork_evidence_sha256'):
            del source['license'][key]
        self._put('legal/ledger/sources.json', json.dumps({'schema_version': SCHEMA, 'sources': [source]}).encode())
        with self.assertRaises(TokenValidationError) as caught:
            self.compiler.validate_token(self.valid_raw)
        self.assertIn('vector-art', str(caught.exception))

    def test_altered_license_evidence_fails_closed(self):
        (Path(self.repo) / 'evidence' / 'upstream-license.txt').write_bytes(b'tampered')
        with self.assertRaises(TokenValidationError) as caught:
            self.compiler.validate_token(self.valid_raw)
        self.assertIn('HASH_MISMATCH', str(caught.exception))

    def test_validate_size_limit(self):
        large_token = {'concept_id': 'large', 'paths': [{'d': 'M10'*1000}]}
        large_raw = zlib.compress(json.dumps(large_token).encode())
        self.compiler.max_bytes = 10 # Force fail
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(large_raw)

    def test_decompression_bomb_is_bounded(self):
        bomb = zlib.compress(b'{"version":"v1","paths":["' + (b'A' * 200000) + b'"]}')
        self.assertLess(len(bomb), self.compiler.max_bytes)
        with self.assertRaises(TokenValidationError) as caught:
            self.compiler.validate_token(bomb)
        self.assertIn('Decompressed token exceeds limit', str(caught.exception))

    def test_validate_corrupt_token(self):
        # Test non-zlib string
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(b"not_zlib_compressed")
        # Test invalid json
        invalid_json = zlib.compress(b"not json")
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(invalid_json)

    def test_decoded_json_must_be_object(self):
        for payload in (b'[]', b'"CC0"', b'1', b'null', b'true'):
            raw = zlib.compress(payload)
            with self.assertRaises(TokenValidationError):
                self.compiler.validate_token(raw)
            try:
                self.compiler.compile([raw], runtime_evidence={'compatible': True})
            except CompilationError as exc:
                self.assertIsInstance(exc.__cause__, TokenValidationError)
            except TokenValidationError:
                self.fail('compile should fail the snapshot instead of skipping the token')
            else:
                self.fail('malformed token produced a pack')
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, 'pack.vct')))

    def test_source_evidence_must_be_object(self):
        for evidence in (['CC0'], 'CC0', None, 1):
            tok = copy.deepcopy(self.valid_token)
            tok['source_evidence'] = evidence
            with self.assertRaises(TokenValidationError):
                self.compiler.validate_token(self._raw(tok))
        tok = copy.deepcopy(self.valid_token)
        del tok['source_evidence']
        with self.assertRaises(TokenValidationError):
            self.compiler.validate_token(self._raw(tok))

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
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, 'pack.vct')))

    def test_compile_requires_evidence(self):
        with self.assertRaises(CompilationError):
            self.compiler.compile([self.valid_raw], runtime_evidence=None)

        with self.assertRaises(CompilationError):
            self.compiler.compile([self.valid_raw], runtime_evidence={'compatible': False})

    def test_compile_delta_events(self):
        t1 = self.valid_token.copy()
        raw1 = zlib.compress(json.dumps(t1).encode())

        t2 = self.valid_token.copy()
        t2['concept_id'] = 'test-2'
        raw2 = zlib.compress(json.dumps(t2).encode())

        t3 = self.valid_token.copy()
        t3['concept_id'] = 'test-update'
        t3['source_hash'] = 'new-hash'
        raw3 = zlib.compress(json.dumps(t3).encode())

        prior_pack_meta = {
            'concepts': {
                'test-1': {'source_hash': 'abc'}, # unchanged
                'test-old': {'source_hash': 'def'}, # deleted
                'test-update': {'source_hash': 'old-hash'} # updated
            }
        }

        res = self.compiler.compile([raw1, raw2, raw3], prior_pack_meta=prior_pack_meta, runtime_evidence={'compatible': True})
        events = {e['concept_id']: e['type'] for e in res['change_events']}

        self.assertEqual(events['test-1'], 'unchanged')
        self.assertEqual(events['test-2'], 'added')
        self.assertEqual(events['test-old'], 'deleted')
        self.assertEqual(events['test-update'], 'updated')

    def test_invalid_token_does_not_delete_published_concept(self):
        pack = os.path.join(self.output_dir, 'pack.vct')
        with open(pack, 'wb') as handle:
            handle.write(b'PRIOR-PACK')
        bad = self._raw({'source_evidence': {'license': 'CC0'}, 'concept_id': 'test-1'})
        prior = {'concepts': {'test-1': {'source_hash': 'abc'}, 'test-old': {'source_hash': 'def'}}}
        with self.assertRaises(CompilationError) as caught:
            self.compiler.compile(
                [self.valid_raw, bad],
                prior_pack_meta=prior,
                runtime_evidence={'compatible': True},
            )
        self.assertIsInstance(caught.exception.__cause__, TokenValidationError)
        with open(pack, 'rb') as handle:
            self.assertEqual(handle.read(), b'PRIOR-PACK')

    def test_all_invalid_batch_emits_no_pack(self):
        bad = self._raw({'source_evidence': {'license': 'CC0'}})
        pack = os.path.join(self.output_dir, 'pack.vct')
        with self.assertRaises(CompilationError):
            self.compiler.compile([bad, bad], runtime_evidence={'compatible': True})
        self.assertFalse(os.path.exists(pack))

    def test_duplicate_concept_ids_are_rejected(self):
        first = copy.deepcopy(self.valid_token)
        second = copy.deepcopy(self.valid_token)
        second['source_hash'] = 'def'
        second['paths'] = [{'d': 'M0 0'}]
        raw_first = self._raw(first)
        raw_second = self._raw(second)
        messages = []
        for batch in ((raw_first, raw_second), (raw_second, raw_first)):
            with patch.object(self.compiler, 'deduplicate_geometry', side_effect=AssertionError('pooled duplicates')):
                with self.assertRaises(CompilationError) as caught:
                    self.compiler.compile(list(batch), runtime_evidence={'compatible': True})
            messages.append(str(caught.exception))
        self.assertEqual(messages[0], messages[1])
        self.assertIn('duplicate concept_id: test-1', messages[0])
        self.assertFalse(os.path.exists(os.path.join(self.output_dir, 'pack.vct')))

    def test_deterministic_output(self):
        t2 = self.valid_token.copy()
        t2['concept_id'] = 'test-2'
        raw2 = zlib.compress(json.dumps(t2).encode())

        # Order shouldn't matter
        res1 = self.compiler.compile([self.valid_raw, raw2], runtime_evidence={'compatible': True})
        res2 = self.compiler.compile([raw2, self.valid_raw], runtime_evidence={'compatible': True})

        self.assertEqual(res1['metadata']['sha256'], res2['metadata']['sha256'])

    def test_publish_replaces_on_output_filesystem(self):
        with patch('tools.media_optimizer.compiler.shutil.move', side_effect=AssertionError('cross-device move')):
            real_replace = os.replace
            seen = {}

            def wrapped(src, dst):
                seen['src'] = os.path.abspath(src)
                seen['dst'] = os.path.abspath(dst)
                return real_replace(src, dst)

            with patch('os.replace', side_effect=wrapped):
                self.compiler.compile([self.valid_raw], runtime_evidence={'compatible': True})
        output = os.path.abspath(self.output_dir)
        self.assertEqual(os.path.dirname(seen['src']), output)
        self.assertEqual(seen['dst'], os.path.join(output, 'pack.vct'))
        self.assertTrue(os.path.isfile(seen['dst']))

    def test_failed_replace_keeps_live_pack(self):
        pack = os.path.join(self.output_dir, 'pack.vct')
        with open(pack, 'wb') as handle:
            handle.write(b'PRIOR-PACK')
        with patch('os.replace', side_effect=OSError('EXDEV')):
            with self.assertRaises(DiskSpaceError):
                self.compiler.compile([self.valid_raw], runtime_evidence={'compatible': True})
        with open(pack, 'rb') as handle:
            self.assertEqual(handle.read(), b'PRIOR-PACK')
        leftovers = [name for name in os.listdir(self.output_dir) if name.startswith('.pack-')]
        self.assertEqual(leftovers, [])

    @patch('shutil.disk_usage')
    def test_insufficient_disk_space(self, mock_disk):
        mock_disk.return_value = (1000, 1000, 0)
        with self.assertRaises(DiskSpaceError):
            self.compiler.compile([self.valid_raw], runtime_evidence={'compatible': True})

    def test_output_filesystem_disk_space(self):
        output = os.path.abspath(self.output_dir)

        def usage(path):
            if os.path.abspath(path) == output:
                return (1000, 1000, 0)
            return (1 << 40, 0, 1 << 40)

        with patch('shutil.disk_usage', side_effect=usage):
            with self.assertRaises(DiskSpaceError):
                self.compiler.compile([self.valid_raw], runtime_evidence={'compatible': True})
        self.assertFalse(os.path.exists(os.path.join(self.output_dir, 'pack.vct')))

if __name__ == '__main__':
    unittest.main()
