import hashlib
import os
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.media_qa.media_license_validator import validate_media_asset

class TestMediaLicenseValidator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_compliant_cc0_asset_passes(self):
        file_path = os.path.join(self.temp_dir.name, "hallo.mp3")
        content = b"ID3_MOCK_AUDIO_DATA_FOR_PRONUNCIATION"
        with open(file_path, 'wb') as f:
            f.write(content)
        sha = hashlib.sha256(content).hexdigest()

        record = {
            'asset_id': 'audio_de_hallo',
            'media_type': 'audio',
            'mime_type': 'audio/mpeg',
            'license_id': 'CC0-1.0',
            'source_url': 'https://example.org/audio/hallo.mp3',
            'sha256': sha,
        }
        ok, msg = validate_media_asset(record, file_path)
        self.assertTrue(ok)
        self.assertEqual(msg, "MEDIA_ASSET_VALID")

    def test_hash_mismatch_fails_closed(self):
        file_path = os.path.join(self.temp_dir.name, "buch.png")
        with open(file_path, 'wb') as f:
            f.write(b"PNG_MOCK_IMAGE_DATA")

        record = {
            'asset_id': 'img_buch',
            'media_type': 'image',
            'mime_type': 'image/png',
            'license_id': 'CC-BY-4.0',
            'source_url': 'https://example.org/img/buch.png',
            'sha256': '0000000000000000000000000000000000000000000000000000000000000000',
        }
        ok, msg = validate_media_asset(record, file_path)
        self.assertFalse(ok)
        self.assertIn("HASH_MISMATCH", msg)

    def test_unauthorized_proprietary_license_rejected(self):
        record = {
            'asset_id': 'img_commercial',
            'media_type': 'image',
            'mime_type': 'image/jpeg',
            'license_id': 'ALL_RIGHTS_RESERVED',
            'source_url': 'https://example.org/stock.jpg',
        }
        ok, msg = validate_media_asset(record)
        self.assertFalse(ok)
        self.assertIn("UNAUTHORIZED_LICENSE", msg)

if __name__ == "__main__":
    unittest.main()
