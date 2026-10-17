import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.audio_pronunciation.admission import process_candidates

class TestAudioAdmissionGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Create some mock valid files
        self.valid_ogg = self.root / 'valid.ogg'
        self.valid_ogg.write_bytes(b'OggS' + b'\x00' * 100)
        self.valid_ogg_sha = self._sha256(self.valid_ogg)

        self.valid_wav = self.root / 'valid.wav'
        self.valid_wav.write_bytes(b'RIFF....WAVE' + b'\x00' * 100)
        self.valid_wav_sha = self._sha256(self.valid_wav)

        self.invalid_file = self.root / 'invalid.txt'
        self.invalid_file.write_bytes(b'This is not an audio file.')
        self.invalid_file_sha = self._sha256(self.invalid_file)

        self.oversized_file = self.root / 'oversized.ogg'
        # just mock the size by creating a file if we could, but let's just make it a smaller file
        # and test the size limit via monkey patching if needed, or actually write 1MB+ if fast
        self.oversized_file.write_bytes(b'OggS' + b'\x00' * (1024 * 1024 + 10))
        self.oversized_file_sha = self._sha256(self.oversized_file)

        # Mock Ledger
        self.ledger = {
            "schema_version": "1.0.0",
            "sources": [
                {
                    "source_id": "test.source.valid",
                    "kind": "pronunciation",
                    "status": "APPROVED_FOR_REDISTRIBUTION"
                },
                {
                    "source_id": "test.source.unapproved",
                    "kind": "pronunciation",
                    "status": "REVIEW_REQUIRED"
                },
                {
                    "source_id": "test.source.wrongkind",
                    "kind": "dictionary",
                    "status": "APPROVED_FOR_REDISTRIBUTION"
                }
            ]
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def _sha256(self, path):
        import hashlib
        d = hashlib.sha256()
        d.update(path.read_bytes())
        return d.hexdigest()

    def test_valid_admission(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 0)

    def test_changed_bytes_hash_mismatch(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "valid.ogg",
            "sha256": "fakehash" * 8, # 64 chars
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("SHA256 mismatch", rejected[0]['rejection_reason'])

    def test_wrong_locale(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "INVALID LOCALE!",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Invalid locale", rejected[0]['rejection_reason'])

    def test_malformed_file(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "invalid.txt",
            "sha256": self.invalid_file_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Invalid file format", rejected[0]['rejection_reason'])

    def test_unlicensed_audio(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.missing",
            "human_recorded": True,
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("rights missing", rejected[0]['rejection_reason'])

    def test_unapproved_audio(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.unapproved",
            "human_recorded": True,
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("rights missing or unapproved", rejected[0]['rejection_reason'])

    def test_oversized_sample(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "oversized.ogg",
            "sha256": self.oversized_file_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("File too large", rejected[0]['rejection_reason'])

    def test_tts_rejected(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": False,
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Must be human_recorded", rejected[0]['rejection_reason'])

    def test_remote_rejected(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "https://example.com/audio.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Remote audio not allowed", rejected[0]['rejection_reason'])

    def test_biometric_rejected(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "biometric_profile": "xyz123",
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Biometric", rejected[0]['rejection_reason'])

    def test_duration_rejected(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg",
            "duration_ms": 15000
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("duration too long", rejected[0]['rejection_reason'])

    def test_channels_rejected(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg",
            "channels": 3
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Too many channels", rejected[0]['rejection_reason'])

    def test_sample_rate_rejected(self):
        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "valid.ogg",
            "sha256": self.valid_ogg_sha,
            "format": "ogg",
            "sample_rate": 8000
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Unsupported sample rate", rejected[0]['rejection_reason'])

    def test_truncated_file(self):
        # Even though a truncated file just fails hash, we test it explicitly.
        truncated_file = self.root / 'trunc.ogg'
        truncated_file.write_bytes(b'Ogg') # missing S
        truncated_file_sha = self._sha256(truncated_file)

        candidates = [{
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": "test.source.valid",
            "human_recorded": True,
            "artifact_path": "trunc.ogg",
            "sha256": truncated_file_sha,
            "format": "ogg"
        }]
        accepted, rejected = process_candidates(candidates, self.ledger, self.root)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("malformed header", rejected[0]['rejection_reason'])

if __name__ == '__main__':
    unittest.main()
