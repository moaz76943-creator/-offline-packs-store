import unittest
import json
import wave
import struct
from pathlib import Path
import tempfile
import shutil

from tools.audio_pronunciation.admission import evaluate, sha256_file, MAX_FILE_SIZE

class TestAudioAdmission(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.audio_dir = self.temp_dir / "audio"
        self.audio_dir.mkdir()
        self.ledger_path = self.temp_dir / "ledger.json"
        self.metadata_path = self.temp_dir / "metadata.json"
        self.output_path = self.temp_dir / "output.json"

        self.ledger = {
            "sources": [
                {
                    "source_id": "verified_source",
                    "status": "APPROVED_FOR_REDISTRIBUTION",
                    "license": {"evidence_path": "path/to/evidence"}
                }
            ]
        }
        with self.ledger_path.open('w') as f:
            json.dump(self.ledger, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def create_wav_file(self, filename, duration=1.0, channels=1, framerate=44100, sampwidth=2):
        path = self.audio_dir / filename
        with wave.open(str(path), 'wb') as w:
            w.setnchannels(channels)
            w.setsampwidth(sampwidth)
            w.setframerate(framerate)
            nframes = int(duration * framerate)
            data = struct.pack(f"<{nframes*channels}h", *([0] * nframes * channels))
            w.writeframes(data)
        return path

    def write_metadata(self, metadata):
        with self.metadata_path.open('w') as f:
            json.dump(metadata, f)

    def test_valid_audio(self):
        self.create_wav_file("test.wav", duration=2.0)
        metadata = [{
            "file_path": "test.wav",
            "source_id": "verified_source",
            "lexical_id": "lex1",
            "locale": "en",
            "attribution": "Attribution string"
        }]
        self.write_metadata(metadata)

        res = evaluate(self.metadata_path, self.audio_dir, self.ledger_path, self.output_path)
        self.assertEqual(res, 0)

        with self.output_path.open() as f:
            out = json.load(f)
            self.assertEqual(len(out["approved_assets"]), 1)
            self.assertEqual(len(out["quarantined_assets"]), 0)

    def test_missing_locale(self):
        self.create_wav_file("test.wav")
        metadata = [{
            "file_path": "test.wav",
            "source_id": "verified_source",
            "lexical_id": "lex1",
            "attribution": "Attribution string"
        }]
        self.write_metadata(metadata)

        res = evaluate(self.metadata_path, self.audio_dir, self.ledger_path, self.output_path)
        self.assertEqual(res, 1)

        with self.output_path.open() as f:
            out = json.load(f)
            self.assertIn("MISSING_LOCALE", out["quarantined_assets"][0]["quarantine_reasons"])

    def test_truncated_file(self):
        # Write incomplete WAV header
        path = self.audio_dir / "truncated.wav"
        with path.open('wb') as f:
            f.write(b"RIF") # Incomplete header

        metadata = [{
            "file_path": "truncated.wav",
            "source_id": "verified_source",
            "lexical_id": "lex1",
            "locale": "en",
            "attribution": "Attribution string"
        }]
        self.write_metadata(metadata)

        res = evaluate(self.metadata_path, self.audio_dir, self.ledger_path, self.output_path)
        self.assertEqual(res, 1)

        with self.output_path.open() as f:
            out = json.load(f)
            self.assertIn("UNSUPPORTED_FORMAT", out["quarantined_assets"][0]["quarantine_reasons"])

    def test_missing_file(self):
        metadata = [{
            "file_path": "missing.wav",
            "source_id": "verified_source",
            "lexical_id": "lex1",
            "locale": "en",
            "attribution": "Attribution string"
        }]
        self.write_metadata(metadata)

        res = evaluate(self.metadata_path, self.audio_dir, self.ledger_path, self.output_path)
        self.assertEqual(res, 1)

        with self.output_path.open() as f:
            out = json.load(f)
            self.assertEqual(len(out["approved_assets"]), 0)
            self.assertEqual(len(out["quarantined_assets"]), 1)
            self.assertIn("FILE_MISSING", out["quarantined_assets"][0]["quarantine_reasons"])

    def test_duration_too_long(self):
        self.create_wav_file("long.wav", duration=6.0) # MAX is 5.0
        metadata = [{
            "file_path": "long.wav",
            "source_id": "verified_source",
            "lexical_id": "lex1",
            "locale": "en",
            "attribution": "Attribution string"
        }]
        self.write_metadata(metadata)

        res = evaluate(self.metadata_path, self.audio_dir, self.ledger_path, self.output_path)
        self.assertEqual(res, 1)

        with self.output_path.open() as f:
            out = json.load(f)
            self.assertEqual(len(out["quarantined_assets"]), 1)
            self.assertIn("DURATION_TOO_LONG", out["quarantined_assets"][0]["quarantine_reasons"])

    def test_file_too_large(self):
        path = self.audio_dir / "large.wav"
        with path.open('wb') as f:
            f.write(b"0" * (MAX_FILE_SIZE + 1))

        metadata = [{
            "file_path": "large.wav",
            "source_id": "verified_source",
            "lexical_id": "lex1",
            "locale": "en",
            "attribution": "Attribution string"
        }]
        self.write_metadata(metadata)

        res = evaluate(self.metadata_path, self.audio_dir, self.ledger_path, self.output_path)
        self.assertEqual(res, 1)

        with self.output_path.open() as f:
            out = json.load(f)
            self.assertIn("FILE_TOO_LARGE", out["quarantined_assets"][0]["quarantine_reasons"])

    def test_unlicensed_source(self):
        self.create_wav_file("test.wav")
        metadata = [{
            "file_path": "test.wav",
            "source_id": "unverified_source",
            "lexical_id": "lex1",
            "locale": "en",
            "attribution": "Attribution string"
        }]
        self.write_metadata(metadata)

        res = evaluate(self.metadata_path, self.audio_dir, self.ledger_path, self.output_path)
        self.assertEqual(res, 1)

        with self.output_path.open() as f:
            out = json.load(f)
            self.assertIn("UNVERIFIED_SOURCE", out["quarantined_assets"][0]["quarantine_reasons"])

    def test_sha256_mismatch(self):
        path = self.create_wav_file("test.wav")
        metadata = [{
            "file_path": "test.wav",
            "source_id": "verified_source",
            "lexical_id": "lex1",
            "locale": "en",
            "attribution": "Attribution string",
            "sha256": "wrong_hash"
        }]
        self.write_metadata(metadata)

        res = evaluate(self.metadata_path, self.audio_dir, self.ledger_path, self.output_path)
        self.assertEqual(res, 1)

        with self.output_path.open() as f:
            out = json.load(f)
            self.assertIn("SHA256_MISMATCH", out["quarantined_assets"][0]["quarantine_reasons"])

if __name__ == '__main__':
    unittest.main()
