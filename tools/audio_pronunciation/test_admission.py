import unittest
import json
import tempfile
from pathlib import Path
import wave
import struct
import os
import hashlib

from tools.audio_pronunciation.admission import evaluate, check_audio_file, MAX_SIZE_BYTES, valid_hash

class TestAudioAdmission(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def create_wav(self, name, duration=1.0, valid=True, fake_size=False):
        p = self.tmp_dir / name
        if not valid:
            p.write_bytes(b"INVALID DATA")
            return str(p)

        with wave.open(str(p), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            frames = int(44100 * duration)
            w.writeframes(struct.pack('h'*frames, *(0 for _ in range(frames))))

        if fake_size:
            # Append zeros to make it artificially large
            with open(str(p), 'ab') as f:
                f.write(b'\0' * (MAX_SIZE_BYTES + 1024))

        return str(p)

    def test_valid_audio(self):
        wav = self.create_wav("valid.wav", duration=1.0)
        h = valid_hash(wav)
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": wav,
                    "sha256": h,
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }

        errors, approved = evaluate(manifest, ledger)
        self.assertEqual(errors, [])
        self.assertEqual(len(approved), 1)

    def test_synthesized_audio_rejected(self):
        wav = self.create_wav("synth.wav", duration=1.0)
        h = valid_hash(wav)
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": wav,
                    "sha256": h,
                    "source": {"source_id": "src1", "tts": True}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: SYNTHESIZED_AUDIO_REJECTED", errors)
        self.assertEqual(len(approved), 0)

    def test_remote_audio_rejected(self):
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": "https://example.com/audio.wav",
                    "sha256": "fakehash",
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: REMOTE_AUDIO_REJECTED", errors)

    def test_unlicensed_audio_rejected(self):
        wav = self.create_wav("unlicensed.wav", duration=1.0)
        h = valid_hash(wav)
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": wav,
                    "sha256": h,
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "UNSUPPORTED"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: BLOCKED_LICENSE", errors)

    def test_malformed_audio(self):
        wav = self.create_wav("malformed.wav", valid=False)
        h = valid_hash(wav)
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": wav,
                    "sha256": h,
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: MALFORMED_FILE", errors)

    def test_oversized_samples(self):
        wav = self.create_wav("large.wav", fake_size=True)
        h = valid_hash(wav)
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": wav,
                    "sha256": h,
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: FILE_TOO_LARGE", errors)

    def test_too_long_samples(self):
        p = self.tmp_dir / "long.wav"
        with wave.open(str(p), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(100)
            frames = 600
            w.writeframes(struct.pack('b'*frames, *(0 for _ in range(frames))))

        h = valid_hash(str(p))
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": str(p),
                    "sha256": h,
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: FILE_TOO_LONG", errors)

    def test_invalid_locale(self):
        wav = self.create_wav("locale.wav", duration=1.0)
        h = valid_hash(wav)
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "invalid locale",
                    "lexical_id": "lex1",
                    "audio_path": wav,
                    "sha256": h,
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: INVALID_LOCALE", errors)

    def test_changed_bytes(self):
        wav = self.create_wav("changed.wav", duration=1.0)
        h = valid_hash(wav)

        # Modify the file, but keep it a valid wav (modify data, not header)
        with open(wav, 'r+b') as f:
            f.seek(44) # Skip wav header
            f.write(b'\xFF')

        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": wav,
                    "sha256": h, # The old hash
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: HASH_MISMATCH", errors)

    def test_missing_sha256(self):
        wav = self.create_wav("missing_sha.wav", duration=1.0)
        manifest = {
            "assets": [
                {
                    "record_id": "rec1",
                    "locale": "en-US",
                    "lexical_id": "lex1",
                    "audio_path": wav,
                    "source": {"source_id": "src1"}
                }
            ]
        }
        ledger = {
            "sources": [
                {
                    "source_id": "src1",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"id": "CC0-1.0"}
                }
            ]
        }
        errors, approved = evaluate(manifest, ledger)
        self.assertIn("rec1: MISSING_SHA256", errors)


if __name__ == '__main__':
    unittest.main()
