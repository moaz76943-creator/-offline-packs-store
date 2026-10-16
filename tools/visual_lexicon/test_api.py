import unittest
import json
import os
from tools.visual_lexicon.api import ConceptRegistry
from tools.visual_lexicon.codec import calculate_hash

class TestConceptRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = ConceptRegistry()
        self.valid_token = {
            "version": 1,
            "concept_id": "test_concept",
            "viewBox": "0 0 24 24",
            "paths": [
                {
                    "d": "M12 2L2 22h20L12 2z",
                    "fill": "#000000"
                }
            ],
            "palette": ["#000000"],
            "semantic_label": "triangle",
            "source_evidence": {
                "author": "Test Author",
                "license": "CC0",
                "source": "https://example.com/test"
            }
        }

    def test_valid_token_registration_and_loading(self):
        compressed = self.registry.register_concept(self.valid_token)
        self.assertTrue(len(compressed) < 2048)

        loaded_token = self.registry.load_concept(compressed)
        self.assertEqual(loaded_token['concept_id'], self.valid_token['concept_id'])
        self.assertEqual(loaded_token['paths'], self.valid_token['paths'])

    def test_invalid_license_rejection(self):
        invalid_token = self.valid_token.copy()
        invalid_token['source_evidence'] = {
            "author": "Test Author",
            "license": "CC-BY",  # Not CC0 or Public Domain
            "source": "https://example.com/test"
        }
        with self.assertRaisesRegex(ValueError, "is not one of"):
            self.registry.register_concept(invalid_token)

    def test_oversized_vector_rejection(self):
        large_token = self.valid_token.copy()
        # Add many paths to make it large
        large_token['paths'] = [{"d": f"M{i} {i} L{i+1} {i+1}z"} for i in range(51)]
        with self.assertRaisesRegex(ValueError, "is too long"):
            self.registry.register_concept(large_token)

    def test_malformed_token_rejection(self):
        malformed_token = self.valid_token.copy()
        del malformed_token['version']
        with self.assertRaisesRegex(ValueError, "Schema validation failed"):
            self.registry.register_concept(malformed_token)

    def test_concept_identity_collision(self):
        # Register first concept
        self.registry.register_concept(self.valid_token)

        # Modify concept but keep same concept_id
        colliding_token = self.valid_token.copy()
        colliding_token['paths'] = [{"d": "M0 0 L1 1z"}]

        with self.assertRaisesRegex(ValueError, "Concept identity collision"):
            self.registry.register_concept(colliding_token)

    def test_incremental_updates(self):
        token1 = self.valid_token.copy()
        token1['concept_id'] = 'concept1'

        token2 = self.valid_token.copy()
        token2['concept_id'] = 'concept2'

        # Initial addition
        changes = self.registry.process_incremental_updates([token1, token2])
        self.assertIn('concept1', changes['added'])
        self.assertIn('concept2', changes['added'])
        self.assertEqual(len(changes['unchanged']), 0)

        # Unchanged
        changes = self.registry.process_incremental_updates([token1])
        self.assertIn('concept1', changes['unchanged'])

        # Collision/failure
        token1_colliding = token1.copy()
        token1_colliding['paths'] = [{"d": "M0 0 L1 1z"}]
        changes = self.registry.process_incremental_updates([token1_colliding])
        self.assertEqual(len(changes['failed']), 1)
        self.assertEqual(changes['failed'][0]['concept_id'], 'concept1')
        self.assertIn("Concept identity collision", changes['failed'][0]['error'])

if __name__ == '__main__':
    unittest.main()
