import unittest
import zlib
import hashlib
import json
from tools.visual_lexicon.encoder import TokenEncoder
from tools.visual_lexicon.validator import ValidationError

class TestTokenEncoder(unittest.TestCase):
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

    def test_encode_success(self):
        compressed_bytes, sha256_hash = TokenEncoder.encode(self.valid_token)

        # Verify it returns bytes and a string hash
        self.assertIsInstance(compressed_bytes, bytes)
        self.assertIsInstance(sha256_hash, str)
        self.assertEqual(len(sha256_hash), 64)

        # Verify decompression gives back canonical json
        decompressed_bytes = zlib.decompress(compressed_bytes)
        canonical_json = decompressed_bytes.decode('utf-8')

        decoded_token = json.loads(canonical_json)
        self.assertEqual(decoded_token, self.valid_token)

        # Verify hash
        self.assertEqual(hashlib.sha256(decompressed_bytes).hexdigest(), sha256_hash)

    def test_oversized_token(self):
        # Generate paths that when compressed exceed 2048 bytes but stay under MAX_PATHS (50)
        # Random data doesn't compress well.
        import random
        random.seed(42)

        long_paths = []
        for _ in range(50):
            path = "M0 0 " + " ".join(f"L{random.randint(0, 1000)} {random.randint(0, 1000)}" for _ in range(50))
            long_paths.append(path)

        self.valid_token['paths'] = long_paths

        with self.assertRaises(ValueError) as ctx:
            TokenEncoder.encode(self.valid_token)
        self.assertIn("exceeds max size", str(ctx.exception))

    def test_invalid_token_rejected(self):
        del self.valid_token['version']
        with self.assertRaises(ValidationError):
            TokenEncoder.encode(self.valid_token)
