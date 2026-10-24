import unittest
import sys
import os

# Add the parent directory to sys.path so we can import utils
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import utils

class TestUtils(unittest.TestCase):
    def test_dummy_webp_type(self):
        """Test that dummy_webp is a bytes object."""
        self.assertIsInstance(utils.dummy_webp, bytes)

    def test_dummy_webp_length(self):
        """Test that dummy_webp has the correct length for a minimal WebP."""
        self.assertEqual(len(utils.dummy_webp), 53)

    def test_dummy_webp_content_riff(self):
        """Test that dummy_webp starts with the RIFF header."""
        self.assertTrue(utils.dummy_webp.startswith(b'RIFF'))

    def test_dummy_webp_content_webp(self):
        """Test that dummy_webp contains the WEBP signature."""
        self.assertIn(b'WEBP', utils.dummy_webp)

    def test_dummy_webp_content_vp8(self):
        """Test that dummy_webp contains the VP8 chunk."""
        self.assertIn(b'VP8', utils.dummy_webp)

if __name__ == '__main__':
    unittest.main()
