import unittest
import os
import tempfile
import shutil
import json
from pathlib import Path
from tools.visual_lexicon.schema import validate_token, validate_manifest
from tools.visual_lexicon.core import encode_token, decode_token, MAX_COMPRESSED_SIZE
from tools.visual_lexicon.store import ConceptStore

class TestVisualLexicon(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.store = ConceptStore(root_dir=self.test_dir)
        self.valid_token = {
            'concept_id': 'test.concept.1',
            'version': 1,
            'viewBox': [0, 0, 24, 24],
            'paths': ['M 10 10 L 20 20 Z'],
            'palette': ['#000', '#FFFFFF'],
            'semantic_label': 'A test shape'
        }
        self.valid_manifest = {
            'concept_id': 'test.concept.1',
            'author': 'synthetic-fixture',
            'fixture_status': 'synthetic',
            'source': 'synthetic-fixture',
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_schema_valid(self):
        self.assertTrue(validate_token(self.valid_token))
        self.assertTrue(validate_manifest(self.valid_manifest))

    def test_schema_invalid_token(self):
        invalid_tokens = [
            (dict(self.valid_token, concept_id=''), "empty concept_id"),
            (dict(self.valid_token, viewBox=[0, 0, 24]), "invalid viewBox length"),
            (dict(self.valid_token, viewBox=[0, 0, '24', 24]), "invalid viewBox type"),
            (dict(self.valid_token, paths=[]), "empty paths"),
            (dict(self.valid_token, paths=['M 10 10 <script> L 20 20']), "invalid path string"),
            (dict(self.valid_token, paths=['M 10 10'] * 51), "too many paths"),
            (dict(self.valid_token, palette=['black']), "invalid hex color"),
            (dict(self.valid_token, semantic_label='a' * 101), "semantic label too long"),
            (dict(self.valid_token, version=0), "invalid version"),
        ]

        for token, reason in invalid_tokens:
            with self.subTest(reason=reason):
                with self.assertRaises(ValueError):
                    validate_token(token)

    def test_schema_invalid_manifest(self):
        invalid_manifests = [
            (dict(self.valid_manifest, license='CC0-1.0'), "license claim"),
            (dict(self.valid_manifest, license='CC-BY-4.0'), "another license claim"),
            (dict(self.valid_manifest, source='https://example.com/cc0-apple'), "external source"),
            (dict(self.valid_manifest, fixture_status='approved'), "non-synthetic status"),
            (dict(self.valid_manifest, author=''), "empty author"),
            ({k: v for k, v in self.valid_manifest.items() if k != 'fixture_status'}, "missing fixture status"),
        ]

        for manifest, reason in invalid_manifests:
            with self.subTest(reason=reason):
                with self.assertRaises(ValueError):
                    validate_manifest(manifest)

    def test_encode_decode_roundtrip(self):
        compressed, h = encode_token(self.valid_token)
        self.assertLess(len(compressed), MAX_COMPRESSED_SIZE)

        decoded = decode_token(compressed)
        self.assertEqual(decoded, self.valid_token)

    def test_oversized_token(self):
        # Create an artificially huge token
        large_token = dict(self.valid_token)
        large_token['paths'] = ['M ' + ' '.join(str(i) for i in range(10000))]

        with self.assertRaises(ValueError) as ctx:
            encode_token(large_token)
        self.assertIn('too large', str(ctx.exception))

    def test_store_incremental_updates(self):
        # Add initial
        self.store.add_token('test.concept.1', self.valid_token, self.valid_manifest)

        # Verify exists and reads correctly
        retrieved = self.store.get_token('test.concept.1')
        self.assertEqual(retrieved, self.valid_token)

        # Verify manifest update
        manifest = self.store._load_manifest()
        import copy
        manifest_copy = copy.deepcopy(manifest)
        self.assertIn('test.concept.1', manifest)
        self.assertEqual(manifest['test.concept.1']['fixture_status'], 'synthetic')
        self.assertNotIn('license', manifest['test.concept.1'])
        self.assertIn('hash', manifest['test.concept.1'])

        # Update token (new version)
        updated_token = dict(self.valid_token, version=2)
        self.store.add_token('test.concept.1', updated_token, self.valid_manifest)

        # Verify update
        retrieved_updated = self.store.get_token('test.concept.1')
        self.assertEqual(retrieved_updated['version'], 2)

        # Need to deep load because _load_manifest returns cached mutable object
        with open(self.store.manifest_path, 'r') as f:
            manifest_updated = json.load(f)

        self.assertNotEqual(manifest_copy['test.concept.1']['hash'], manifest_updated['test.concept.1']['hash'])

    def test_store_concept_collision(self):
        mismatched_token = dict(self.valid_token, concept_id='other.concept')
        with self.assertRaises(ValueError) as ctx:
            self.store.add_token('test.concept.1', mismatched_token, self.valid_manifest)
        self.assertIn('mismatch', str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
