import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.media_qa.media_license_validator import validate_media_metadata

class TestMediaLicenseValidator(unittest.TestCase):
    def test_valid_audio_asset(self):
        entry = {
            "media_id": "audio_de_buch",
            "license": "CC0-1.0",
            "mime_type": "audio/ogg",
            "size_bytes": 45000,
            "provenance": "LinguaLibre"
        }
        valid, errors = validate_media_metadata(entry)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_unapproved_license_and_size_exceeded(self):
        entry = {
            "media_id": "huge_audio",
            "license": "ALL_RIGHTS_RESERVED",
            "mime_type": "audio/ogg",
            "size_bytes": 3 * 1024 * 1024 # 3MB
        }
        valid, errors = validate_media_metadata(entry)
        self.assertFalse(valid)
        self.assertTrue(any("Unapproved" in e for e in errors))
        self.assertTrue(any("exceeds maximum bound" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
