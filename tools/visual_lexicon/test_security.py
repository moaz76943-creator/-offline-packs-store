import unittest
import zlib
from tools.visual_lexicon.core import decode_token

class TestSecurity(unittest.TestCase):
    def test_malicious_payload(self):
        # A payload larger than MAX_TOKEN_SIZE
        payload = b'A' * 3000

        with self.assertRaises(ValueError):
            decode_token(payload)

    def test_invalid_compressed_data(self):
        # Data smaller than MAX_TOKEN_SIZE but invalid zlib format
        payload = b'A' * 1000
        with self.assertRaises(ValueError):
            decode_token(payload)

    def test_invalid_json(self):
        # Valid zlib but invalid JSON
        payload = zlib.compress(b'{invalid json}')
        with self.assertRaises(ValueError):
            decode_token(payload)
