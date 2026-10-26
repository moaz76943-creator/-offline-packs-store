import unittest
from tools.svg_optimizer.verifier import SvgVerifier
from tools.svg_optimizer.optimizer import SvgOptimizer
from tools.visual_lexicon.core import encode_token, decode_token

class TestSvgVerifier(unittest.TestCase):
    def setUp(self):
        self.verifier = SvgVerifier()
        self.opt = SvgOptimizer()
        self.metadata = {'concept_id': 'test-1', 'semantic_label': 'test'}

    def test_geometry_bounds_ok(self):
        token = {'viewBox': [0, 0, 100, 100], 'paths': ['M 0 0 L 100 100']}
        self.verifier.verify_geometry_bounds(token)  # Should not raise

    def test_geometry_bounds_overflow(self):
        token = {'viewBox': [0, 0, 100, 100], 'paths': ['M 0 0 L 100000 100000']}
        with self.assertRaisesRegex(ValueError, "Geometry bounds overflow"):
            self.verifier.verify_geometry_bounds(token)

    def test_size_limit(self):
        # 2048 limit check
        large_bytes = b'x' * 2049
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.verifier.verify_size(large_bytes)

        small_bytes = b'x' * 100
        self.verifier.verify_size(small_bytes)  # Should not raise

    def test_round_trip_and_determinism(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 10 10 L 90 90"/></svg>'
        token1 = self.opt.optimize(svg, self.metadata)
        token2 = self.opt.optimize(svg, self.metadata)

        # Test determinism before compression
        self.assertEqual(token1, token2)

        # Encode
        comp1, hash1 = encode_token(token1)
        comp2, hash2 = encode_token(token2)

        # Test bytes determinism
        self.verifier.verify_deterministic(comp1, comp2)
        self.assertEqual(hash1, hash2)

        # Test size
        self.verifier.verify_size(comp1)

        # Test round trip
        dec1 = decode_token(comp1)
        # Exclude metadata like source which might not survive round trip unless explicitly supported
        # But core schema validation only cares about required keys.
        self.assertEqual(token1['paths'], dec1['paths'])

if __name__ == '__main__':
    unittest.main()
