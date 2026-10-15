import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
import hashlib

from tools.audio_pronunciation.admission import process_audio_file, MAX_FILE_SIZE, MAX_DURATION_MS

class TestAudioAdmission(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root_dir = Path(self.temp_dir)

        self.ledger_sources = {
            "valid_source": {
                "source_id": "valid_source",
                "kind": "pronunciation",
                "status": "APPROVED_FOR_REDISTRIBUTION"
            },
            "unapproved_source": {
                "source_id": "unapproved_source",
                "kind": "pronunciation",
                "status": "REVIEW_REQUIRED"
            },
            "wrong_kind": {
                "source_id": "wrong_kind",
                "kind": "dictionary",
                "status": "APPROVED_FOR_REDISTRIBUTION"
            }
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def create_mock_audio(self, filename, content=b'RIFF\x00\x00\x00\x00WAVE'):
        path = self.root_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(content)
        size = len(content)
        sha256 = hashlib.sha256(content).hexdigest()
        return str(path.relative_to(self.root_dir)), size, sha256

    def test_valid_wav_admission(self):
        file_path, size, sha256 = self.create_mock_audio("audio.wav")
        entry = {
            "lexical_id": "word_1",
            "locale": "en-US",
            "variant": "genam",
            "source_id": "valid_source",
            "format": "wav",
            "file_path": file_path,
            "sha256": sha256,
            "size_bytes": size,
            "is_human": True
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertIsNone(error)

    def test_missing_rights(self):
        file_path, size, sha256 = self.create_mock_audio("audio.wav")
        entry = {
            "lexical_id": "word_1",
            "locale": "en-US",
            "variant": "genam",
            "source_id": "unapproved_source",
            "format": "wav",
            "file_path": file_path,
            "sha256": sha256,
            "size_bytes": size,
            "is_human": True
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertIn("not APPROVED_FOR_REDISTRIBUTION", error)

    def test_missing_source_in_ledger(self):
        file_path, size, sha256 = self.create_mock_audio("audio.wav")
        entry = {
            "lexical_id": "word_1",
            "locale": "en-US",
            "variant": "genam",
            "source_id": "nonexistent_source",
            "format": "wav",
            "file_path": file_path,
            "sha256": sha256,
            "size_bytes": size,
            "is_human": True
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertIn("not found in legal ledger", error)

    def test_wrong_locale(self):
        file_path, size, sha256 = self.create_mock_audio("audio.wav")
        entry = {
            "lexical_id": "word_1",
            "locale": "invalid_locale!",
            "variant": "genam",
            "source_id": "valid_source",
            "format": "wav",
            "file_path": file_path,
            "sha256": sha256,
            "size_bytes": size,
            "is_human": True
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertEqual(error, "invalid locale format")

    def test_tts_rejected(self):
        file_path, size, sha256 = self.create_mock_audio("audio.wav")
        entry = {
            "lexical_id": "word_1",
            "locale": "en-US",
            "variant": "genam",
            "source_id": "valid_source",
            "format": "wav",
            "file_path": file_path,
            "sha256": sha256,
            "size_bytes": size,
            "is_human": False
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertIn("not human-recorded audio", error)

    def test_truncated_file(self):
        file_path, size, sha256 = self.create_mock_audio("audio.wav")
        # Modify the actual file so size matches but sha256 fails, or size fails
        # Let's test size mismatch first
        entry = {
            "lexical_id": "word_1",
            "locale": "en-US",
            "variant": "genam",
            "source_id": "valid_source",
            "format": "wav",
            "file_path": file_path,
            "sha256": sha256,
            "size_bytes": size + 1,  # wrong size
            "is_human": True
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertIn("file size mismatch", error)

        # Test hash mismatch
        entry["size_bytes"] = size
        entry["sha256"] = "a" * 64
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertIn("hash mismatch", error)

    def test_oversized_sample(self):
        file_path, _, sha256 = self.create_mock_audio("audio.wav", b'R' * (MAX_FILE_SIZE + 1))
        entry = {
            "lexical_id": "word_1",
            "locale": "en-US",
            "variant": "genam",
            "source_id": "valid_source",
            "format": "wav",
            "file_path": file_path,
            "sha256": sha256,
            "size_bytes": MAX_FILE_SIZE + 1,
            "is_human": True
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertIn("file too large", error)

    def test_magic_bytes_mismatch(self):
        file_path, size, sha256 = self.create_mock_audio("audio.ogg", b'NOT_OGG_HEADER')
        entry = {
            "lexical_id": "word_1",
            "locale": "en-US",
            "variant": "genam",
            "source_id": "valid_source",
            "format": "ogg",
            "file_path": file_path,
            "sha256": sha256,
            "size_bytes": size,
            "is_human": True
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertIn("magic bytes mismatch", error)

    def test_remote_audio(self):
        entry = {
            "lexical_id": "word_1",
            "locale": "en-US",
            "variant": "genam",
            "source_id": "valid_source",
            "format": "wav",
            "file_path": "https://example.com/audio.wav",
            "sha256": "0" * 64,
            "size_bytes": 100,
            "is_human": True
        }
        error = process_audio_file(entry, self.ledger_sources, self.root_dir)
        self.assertEqual(error, "remote audio references are not allowed")

if __name__ == '__main__':
    unittest.main()
