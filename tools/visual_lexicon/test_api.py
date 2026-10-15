import unittest
import os
import shutil
import json
from pathlib import Path
from tools.visual_lexicon.api import VisualLexiconAPI

class TestVisualLexiconAPI(unittest.TestCase):
    def setUp(self):
        self.test_dir = 'test_media_icons'
        self.manifest_path = f"{self.test_dir}/manifest.json"

        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

        self.api = VisualLexiconAPI(media_dir=self.test_dir, manifest_path=self.manifest_path)

        self.valid_token = {
            'version': 1,
            'viewBox': '0 0 24 24',
            'paths': ['M12 2L2 22h20L12 2z'],
            'palette': ['#000000'],
            'semantic_label': 'triangle',
            'alt_text': 'A black triangle',
            'author': 'Test Author',
            'source': 'https://example.com',
            'license': 'CC0-1.0'
        }

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_register_and_get_token(self):
        concept_id = "concept-triangle"

        # Register
        token_hash = self.api.register_token(concept_id, self.valid_token)

        # Check files were created
        self.assertTrue(os.path.exists(self.manifest_path))
        self.assertTrue(os.path.exists(f"{self.test_dir}/{token_hash}.vct"))

        # Retrieve
        retrieved_token = self.api.get_token(concept_id)
        self.assertEqual(retrieved_token, self.valid_token)

        # Check manifest content
        with open(self.manifest_path, 'r') as f:
            manifest = json.load(f)
        self.assertEqual(manifest[concept_id], token_hash)

    def test_concept_collision_same_token(self):
        concept_id = "concept-triangle"
        hash1 = self.api.register_token(concept_id, self.valid_token)
        # Registering the exact same token for the same concept should succeed
        hash2 = self.api.register_token(concept_id, self.valid_token)
        self.assertEqual(hash1, hash2)

    def test_concept_collision_different_token(self):
        concept_id = "concept-triangle"
        self.api.register_token(concept_id, self.valid_token)

        # Modify the token slightly
        different_token = self.valid_token.copy()
        different_token['palette'] = ['#FF0000']

        with self.assertRaises(ValueError) as ctx:
            self.api.register_token(concept_id, different_token)
        self.assertIn("Concept collision", str(ctx.exception))

    def test_get_nonexistent_token(self):
        self.assertIsNone(self.api.get_token("nonexistent-concept"))
