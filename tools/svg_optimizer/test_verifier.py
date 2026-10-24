import unittest
from tools.svg_optimizer.verifier import verify_geometry, verify_arc_radii, verify_size_bounds

class TestVerifier(unittest.TestCase):
    def test_bounds_overflow(self):
        paths = ["M 10 10 L 1000000 0"]
        viewBox = [0, 0, 100, 100]
        with self.assertRaises(ValueError):
            verify_geometry(paths, viewBox)

        # Normal bounds should pass
        paths_ok = ["M 10 10 L 90 90"]
        self.assertTrue(verify_geometry(paths_ok, viewBox))

    def test_invalid_arc_radii(self):
        paths_invalid = ["M 10 10 A 0 5 0 0 1 20 20"]
        with self.assertRaises(ValueError):
            verify_arc_radii(paths_invalid)

        paths_invalid_neg = ["M 10 10 A 5 -5 0 0 1 20 20"]
        with self.assertRaises(ValueError):
            verify_arc_radii(paths_invalid_neg)

        paths_ok = ["M 10 10 A 5 5 0 0 1 20 20"]
        self.assertTrue(verify_arc_radii(paths_ok))

    def test_size_limits(self):
        # Limit is 2048
        small_bytes = b'x' * 100
        self.assertTrue(verify_size_bounds(small_bytes, 2048))

        large_bytes = b'x' * 3000
        with self.assertRaises(ValueError):
            verify_size_bounds(large_bytes, 2048)

if __name__ == '__main__':
    unittest.main()
