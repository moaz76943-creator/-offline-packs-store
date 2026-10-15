import unittest
import zlib
from tools.visual_lexicon.encoder import TokenEncoder
from tools.visual_lexicon.decoder import TokenDecoder

class TestTokenDecoder(unittest.TestCase):
    def setUp(self):
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
        self.compressed_bytes, self.sha256_hash = TokenEncoder.encode(self.valid_token)

    def test_decode_success(self):
        decoded_token, decoded_hash = TokenDecoder.decode(self.compressed_bytes)
        self.assertEqual(decoded_token, self.valid_token)
        self.assertEqual(decoded_hash, self.sha256_hash)

    def test_decode_invalid_zlib(self):
        with self.assertRaises(ValueError) as ctx:
            TokenDecoder.decode(b"not compressed data")
        self.assertIn("Failed to decompress", str(ctx.exception))

    def test_decode_invalid_json(self):
        bad_json = b"{invalid json}"
        compressed = zlib.compress(bad_json)
        with self.assertRaises(ValueError) as ctx:
            TokenDecoder.decode(compressed)
        self.assertIn("Failed to decode JSON", str(ctx.exception))

    def test_decode_fails_validation(self):
        # Decode valid json but missing required keys
        invalid_token = {'paths': ['M0 0']}
        import json
        compressed = zlib.compress(json.dumps(invalid_token).encode('utf-8'))
        from tools.visual_lexicon.validator import ValidationError
        with self.assertRaises(ValidationError):
            TokenDecoder.decode(compressed)
