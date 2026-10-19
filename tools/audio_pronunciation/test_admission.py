import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from tools.audio_pronunciation.admission import (
    inspect_audio,
    process_candidates,
)


def _sha256(path):
    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def _put(root, name, value):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return hashlib.sha256(value).hexdigest()


def write_ledger(root, source_id="pronunciation-case", status="APPROVED_FOR_REDISTRIBUTION",
                 kind="pronunciation", schema_version="1.0.0", duplicate=False, drop_review=False,
                 bad_license_hash=False):
    """Temporary test-only ledger. Not a production approval or a real license grant."""
    origin = "https://example.org/pronunciation-case"
    original_sha = _put(root, "evidence/upstream.bin", b"source fixture bytes")
    rights_sha = _put(root, "evidence/rights.txt", b"Test author grants CC0 to fixture data")
    if bad_license_hash:
        rights_sha = "a" * 64
    source = {
        "source_id": source_id,
        "kind": kind,
        "origin_url": origin,
        "publisher": "Example Test Publisher", "author": "Test Author",
        "dataset_version": "1.0",
        "retrieval": {
            "identity": "capture-1",
            "url": origin,
            "date": "2026-10-12",
            "artifact_path": "evidence/upstream.bin",
            "sha256": original_sha,
        },
        "license": {
            "id": "CC0-1.0",
            "evidence_url": origin + "/rights",
            "evidence_path": "evidence/rights.txt",
            "evidence_sha256": rights_sha,
        },
        "status": status,
        "alterations": ["no changes"],
    }
    if not drop_review:
        source["review"] = {"reviewer": "fixture-reviewer", "decision_url": origin + "/review"}
    sources = [source, json.loads(json.dumps(source))] if duplicate else [source]
    ledger = {"schema_version": schema_version, "sources": sources}
    path = Path(root) / "legal" / "ledger" / "sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def _pcm_wav(path, rate, channels, frames, sample_width=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(rate)
        handle.writeframes(b"\x00" * frames * channels * sample_width)


def _ffmpeg(path, codec, rate, channels, seconds):
    layout = "mono" if channels == 1 else "stereo"
    command = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=r={rate}:cl={layout}",
        "-t", str(seconds),
        "-c:a", codec,
        "-ar", str(rate),
        "-ac", str(channels),
        str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class TestAudioAdmissionGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("ffmpeg") is None:
            raise unittest.SkipTest("ffmpeg is required to build container fixtures")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.ledger = write_ledger(self.root)
        self.source_id = self.ledger["sources"][0]["source_id"]

        self.wav = self.root / "short.wav"
        _pcm_wav(self.wav, 16000, 1, 8000)
        self.ogg = self.root / "short.ogg"
        _ffmpeg(self.ogg, "libvorbis", 16000, 1, 0.5)
        self.mp3 = self.root / "short.mp3"
        _ffmpeg(self.mp3, "libmp3lame", 44100, 2, 0.5)
        self.webm = self.root / "short.webm"
        _ffmpeg(self.webm, "libopus", 48000, 1, 0.5)
        self.long_ogg = self.root / "long.ogg"
        _ffmpeg(self.long_ogg, "libvorbis", 16000, 1, 11)
        self.wide = self.root / "wide.wav"
        _pcm_wav(self.wide, 16000, 3, 1600)
        self.low_rate = self.root / "low.wav"
        _pcm_wav(self.low_rate, 8000, 1, 4000)

    def candidate(self, path, **overrides):
        measured = inspect_audio(path.read_bytes(), overrides.get("format", path.suffix.lstrip(".")))
        row = {
            "lexeme_id": "lex.en.test",
            "locale": "en-US",
            "source_id": self.source_id,
            "human_recorded": True,
            "artifact_path": path.name,
            "sha256": _sha256(path),
            "format": path.suffix.lstrip("."),
            "duration_ms": measured["duration_ms"],
            "channels": measured["channels"],
            "sample_rate": measured["sample_rate"],
        }
        row.update(overrides)
        return row

    def test_valid_wav_ogg_mp3_and_webm(self):
        for path in (self.wav, self.ogg, self.mp3, self.webm):
            accepted, rejected = process_candidates([self.candidate(path)], self.ledger, self.root)
            self.assertEqual(rejected, [], path.name)
            self.assertEqual(len(accepted), 1, path.name)
            self.assertTrue(set(accepted[0]).issubset({
                "lexeme_id", "locale", "source_id", "human_recorded", "is_tts",
                "artifact_path", "sha256", "format", "duration_ms", "channels", "sample_rate",
            }))
            measured = inspect_audio(path.read_bytes(), path.suffix.lstrip("."))
            self.assertEqual(accepted[0]["duration_ms"], measured["duration_ms"])
            self.assertEqual(accepted[0]["channels"], measured["channels"])
            self.assertEqual(accepted[0]["sample_rate"], measured["sample_rate"])
            self.assertLessEqual(measured["duration_ms"], 10000)
            self.assertGreater(measured["duration_ms"], 0)

    def test_shallow_ledger_does_not_admit_audio(self):
        shallow = {
            "schema_version": "1.0.0",
            "sources": [{
                "source_id": self.source_id,
                "kind": "pronunciation",
                "status": "APPROVED_FOR_REDISTRIBUTION",
            }],
        }
        path = self.root / "legal" / "ledger" / "sources.json"
        path.write_text(json.dumps(shallow), encoding="utf-8")
        accepted, rejected = process_candidates(
            [self.candidate(self.wav)], json.loads(path.read_text(encoding="utf-8")), self.root)
        self.assertEqual(accepted, [])
        self.assertIn("rights missing or unapproved", rejected[0]["rejection_reason"])

    def test_missing_author_from_canonical_ledger_is_rejected(self):
        ledger = json.loads(json.dumps(self.ledger))
        ledger["sources"][0].pop("author")
        path = self.root / "legal" / "ledger" / "sources.json"
        path.write_text(json.dumps(ledger), encoding="utf-8")
        accepted, rejected = process_candidates(
            [self.candidate(self.wav)], ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("rights missing or unapproved", rejected[0]["rejection_reason"])

    def test_caller_ledger_must_equal_canonical_file(self):
        forged = json.loads(json.dumps(self.ledger))
        forged["sources"][0]["publisher"] = "Forged Publisher"
        accepted, rejected = process_candidates([self.candidate(self.wav)], forged, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("rights missing or unapproved", rejected[0]["rejection_reason"])

    def test_bad_schema_duplicate_review_and_license_hash_rejected(self):
        row = self.candidate(self.wav)
        cases = [
            write_ledger(self.root, schema_version="9.9.9"),
            write_ledger(self.root, duplicate=True),
            write_ledger(self.root, drop_review=True),
            write_ledger(self.root, bad_license_hash=True),
            write_ledger(self.root, status="REVIEW_REQUIRED"),
            write_ledger(self.root, kind="dictionary"),
        ]
        for ledger in cases:
            accepted, rejected = process_candidates([row], ledger, self.root)
            self.assertEqual(accepted, [], ledger)
            self.assertIn("rights missing or unapproved", rejected[0]["rejection_reason"])
        self.ledger = write_ledger(self.root)

    def test_changed_bytes_hash_mismatch(self):
        row = self.candidate(self.wav, sha256="ab" * 32)
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("SHA256 mismatch", rejected[0]["rejection_reason"])

    def test_wrong_locale(self):
        row = self.candidate(self.wav, locale="INVALID LOCALE!")
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("Invalid locale", rejected[0]["rejection_reason"])

    def test_prefix_only_containers_rejected(self):
        samples = {
            "tiny.ogg": (b"OggS", "ogg"),
            "prefix.ogg": (b"OggS" + b"\x00" * 100, "ogg"),
            "prefix.wav": (b"RIFF....WAVE" + b"\x00" * 100, "wav"),
            "prefix.webm": (b"\x1a\x45\xdf\xa3" + b"\x00" * 32, "webm"),
            "prefix.mp3": (b"\xff\xfb\x90\xc0" + b"\x00" * 32, "mp3"),
            "invalid.txt": (b"This is not an audio file.", "ogg"),
        }
        for name, (payload, fmt) in samples.items():
            path = self.root / name
            path.write_bytes(payload)
            row = {
                "lexeme_id": "lex.en.test",
                "locale": "en-US",
                "source_id": self.source_id,
                "human_recorded": True,
                "artifact_path": name,
                "sha256": _sha256(path),
                "format": fmt,
                "duration_ms": 500,
                "channels": 1,
                "sample_rate": 16000,
            }
            accepted, rejected = process_candidates([row], self.ledger, self.root)
            self.assertEqual(accepted, [], name)
            self.assertIn("malformed header", rejected[0]["rejection_reason"])

    def test_missing_source_rejected(self):
        row = self.candidate(self.wav, source_id="missing-source")
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("rights missing", rejected[0]["rejection_reason"])

    def test_oversized_sample(self):
        path = self.root / "oversized.ogg"
        path.write_bytes(b"OggS" + b"\x00" * (1024 * 1024 + 10))
        row = self.candidate(self.wav)
        row["artifact_path"] = path.name
        row["sha256"] = _sha256(path)
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("File too large", rejected[0]["rejection_reason"])

    def test_tts_rejected(self):
        row = self.candidate(self.wav, human_recorded=False, is_tts=True)
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("Must be human_recorded", rejected[0]["rejection_reason"])

    def test_remote_rejected(self):
        row = self.candidate(self.wav, artifact_path="https://example.com/audio.ogg")
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("Remote audio not allowed", rejected[0]["rejection_reason"])

    def test_known_biometric_keys_rejected_and_not_copied(self):
        row = self.candidate(self.wav, biometric_profile="xyz123")
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("Biometric", rejected[0]["rejection_reason"])
        self.assertNotIn("biometric_profile", rejected[0])
        self.assertNotIn("xyz123", json.dumps(rejected[0]))

    def test_voiceprint_speaker_id_and_nested_profile_rejected(self):
        cases = [
            {"voiceprint": "embed-abc"},
            {"speaker_id": "spk-9"},
            {"speaker_profile": {"speaker_id": "spk-9", "voiceprint": [0.2, 0.4]}},
            {"notes": {"speaker": {"id": "hidden"}}},
        ]
        for extra in cases:
            row = self.candidate(self.wav, **extra)
            accepted, rejected = process_candidates([row], self.ledger, self.root)
            self.assertEqual(accepted, [], extra)
            blob = json.dumps(rejected)
            self.assertNotIn("voiceprint", blob)
            self.assertNotIn("spk-9", blob)
            self.assertNotIn("embed-abc", blob)

    def test_long_recording_rejected_when_duration_omitted_or_understated(self):
        measured = inspect_audio(self.long_ogg.read_bytes(), "ogg")
        self.assertGreater(measured["duration_ms"], 10000)
        for declared in (None, 10000, 500, measured["duration_ms"]):
            row = self.candidate(self.long_ogg)
            if declared is None:
                del row["duration_ms"]
            else:
                row["duration_ms"] = declared
            accepted, rejected = process_candidates([row], self.ledger, self.root)
            self.assertEqual(accepted, [], declared)
            self.assertIn("duration too long", rejected[0]["rejection_reason"])

    def test_missing_or_false_duration_rejected_for_short_audio(self):
        row = self.candidate(self.wav)
        del row["duration_ms"]
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("missing or contradictory duration", rejected[0]["rejection_reason"])
        row = self.candidate(self.wav, duration_ms=1)
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("missing or contradictory duration", rejected[0]["rejection_reason"])

    def test_missing_or_false_channels_and_sample_rate_rejected(self):
        row = self.candidate(self.wav)
        del row["channels"]
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertIn("missing or contradictory channels", rejected[0]["rejection_reason"])
        row = self.candidate(self.wav, channels=2)
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("missing or contradictory channels", rejected[0]["rejection_reason"])
        row = self.candidate(self.wav)
        del row["sample_rate"]
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertIn("missing or contradictory sample rate", rejected[0]["rejection_reason"])
        row = self.candidate(self.wav, sample_rate=44100)
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertIn("missing or contradictory sample rate", rejected[0]["rejection_reason"])

    def test_too_many_channels_and_unsupported_rate_come_from_bytes(self):
        wide = inspect_audio(self.wide.read_bytes(), "wav")
        self.assertEqual(wide["channels"], 3)
        row = self.candidate(self.wide, channels=3, sample_rate=wide["sample_rate"], duration_ms=wide["duration_ms"])
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("Too many channels", rejected[0]["rejection_reason"])
        low = inspect_audio(self.low_rate.read_bytes(), "wav")
        self.assertEqual(low["sample_rate"], 8000)
        row = self.candidate(self.low_rate, channels=low["channels"], sample_rate=8000, duration_ms=low["duration_ms"])
        accepted, rejected = process_candidates([row], self.ledger, self.root)
        self.assertEqual(accepted, [])
        self.assertIn("Unsupported sample rate", rejected[0]["rejection_reason"])


if __name__ == "__main__":
    unittest.main()
