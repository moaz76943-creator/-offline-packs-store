"""Synthetic evidence fixtures; never represent published recordings."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave

from tools.factory_extensions.pronunciation_scale.factory import audit, offline_tts_ready


class PronunciationAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog = {"languages": [
            {"id": code, "scripts": [script]} for code, script in
            (("de", "Latn"), ("ar", "Arab"), ("zh", "Hans"), ("ja", "Jpan"), ("yo", "Latn"))
        ], "locale_variants": [{"tag": "zh-Hans-CN", "language_id": "zh", "script": "Hans"}]}
        self.wav = self.root / "sample.wav"
        with wave.open(str(self.wav), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(b"\x00\x00" * 800)
        self.sha = hashlib.sha256(self.wav.read_bytes()).hexdigest()
        self.license_path = self.root / "license.txt"
        self.license_path.write_text("synthetic rights evidence fixture", encoding="utf-8")
        self.source_path = self.root / "source.txt"
        self.source_path.write_text("synthetic original fixture", encoding="utf-8")
        self.ledger = {"sources": [{
            "source_id": "synthetic_source", "kind": "pronunciation", "status": "APPROVED_FOR_REDISTRIBUTION",
            "publisher": "Synthetic publisher", "dataset_version": "v1",
            "origin_url": "https://example.org/original", "review": {"reviewer": "Fixture", "decision_url": "https://example.org/review"},
            "retrieval": {"artifact_path": "source.txt", "sha256": hashlib.sha256(self.source_path.read_bytes()).hexdigest()},
            "license": {"id": "CC0-1.0", "evidence_url": "https://example.org/rights", "evidence_path": "license.txt",
                        "evidence_sha256": hashlib.sha256(self.license_path.read_bytes()).hexdigest()}
        }]}
        self.record = {
            "pronunciation_id": "pron_de_1", "lexeme_id": "lex_de_1", "sense_id": "sense_de_1",
            "language_id": "de", "language_tag": "de", "script": "Latn", "variant_id": "standard",
            "reading": {"notation": "ipa", "value": "ˈhaʊs", "syllables": ["haʊs"], "stress": "primary:first"},
            "evidence": {"source_id": "synthetic_source", "publisher": "Synthetic publisher", "dataset_version": "v1",
                         "record_locator": "fixture:1", "license_id": "CC0-1.0"},
            "audio": [{"asset_id": "asset_1", "kind": "human_recording", "path": "sample.wav", "sha256": self.sha,
                       "license_id": "CC0-1.0", "speaker_id": "speaker_fixture", "rights_url": "https://example.org/rights",
                       "rights_evidence_path": "license.txt", "rights_evidence_sha256": hashlib.sha256(self.license_path.read_bytes()).hexdigest()}]
        }

    def run_audit(self, records=None, ledger=None):
        return audit(self.catalog, self.ledger if ledger is None else ledger,
                     {"metadata_version": "1.0.0", "records": [self.record] if records is None else records},
                     self.root, self.root)

    def test_attested_audio_admitted_and_hash_listed(self):
        result = self.run_audit()
        self.assertEqual(result["coverage"]["de"]["audio_files"], 1)
        self.assertEqual(result["accepted"][0]["asset_id"], "asset_1")
        self.assertEqual(result["blocked"], [])

    def test_empty_production_ledger_blocks_asset(self):
        result = self.run_audit(ledger={"sources": []})
        self.assertEqual(result["coverage"]["de"]["audio_files"], 0)
        self.assertIn("source_not_approved", result["blocked"][0]["reasons"])

    def test_noncommercial_mixed_and_absent_license_blocked(self):
        for license_id in ("CC-BY-NC-SA-4.0", "MIXED", ""):
            with self.subTest(license_id=license_id):
                rec = json.loads(json.dumps(self.record)); rec["audio"][0]["license_id"] = license_id
                self.assertEqual(self.run_audit([rec])["coverage"]["de"]["audio_files"], 0)

    def test_missing_speaker_and_forged_source_proof_blocked(self):
        rec = json.loads(json.dumps(self.record)); del rec["audio"][0]["speaker_id"]
        self.assertIn("speaker_missing", self.run_audit([rec])["blocked"][0]["reasons"])
        ledger = json.loads(json.dumps(self.ledger)); ledger["sources"][0]["retrieval"]["sha256"] = "0" * 64
        self.assertIn("source_not_approved", self.run_audit(ledger=ledger)["blocked"][0]["reasons"])

    def test_wrong_language_script_and_unattested_ipa(self):
        rec = json.loads(json.dumps(self.record)); rec["script"] = "Arab"
        self.assertIn("identity_mismatch", self.run_audit([rec])["blocked"][0]["reasons"])
        rec = json.loads(json.dumps(self.record)); rec["reading"]["value"] = ""
        self.assertIn("reading_unattested", self.run_audit([rec])["blocked"][0]["reasons"])

    def test_tone_and_readings_are_preserved_not_guessed(self):
        rec = json.loads(json.dumps(self.record))
        rec.update({"language_id":"zh", "language_tag":"zh-Hans-CN", "script":"Hans", "variant_id":"reading2"})
        rec["reading"] = {"notation":"ipa", "value":"ma˥˩", "tones":["falling"], "syllables":["ma"]}
        res = self.run_audit([rec])
        self.assertEqual(res["accepted"][0]["reading"]["tones"], ["falling"])
        self.assertEqual(res["coverage"]["zh"]["pronunciation_variants"], 1)

    def test_corrupt_header_extra_channel_large_file_and_mismatch(self):
        rec = json.loads(json.dumps(self.record))
        rec["audio"][0]["sha256"] = "0" * 64
        self.assertIn("audio_invalid", self.run_audit([rec])["blocked"][0]["reasons"])
        self.wav.write_bytes(b"RIFF" + b"not an audio decoder")
        rec["audio"][0]["sha256"] = hashlib.sha256(self.wav.read_bytes()).hexdigest()
        self.assertIn("audio_invalid", self.run_audit([rec])["blocked"][0]["reasons"])
        with wave.open(str(self.wav), "wb") as f:
            f.setnchannels(3); f.setsampwidth(2); f.setframerate(8000); f.writeframes(b"\0" * 4800)
        rec["audio"][0]["sha256"] = hashlib.sha256(self.wav.read_bytes()).hexdigest()
        self.assertIn("audio_invalid", self.run_audit([rec])["blocked"][0]["reasons"])

    def test_traversal_and_device_tts_not_packaged(self):
        rec = json.loads(json.dumps(self.record)); rec["audio"][0]["path"] = "../sample.wav"
        self.assertIn("audio_invalid", self.run_audit([rec])["blocked"][0]["reasons"])
        rec = json.loads(json.dumps(self.record)); rec["audio"][0]["kind"] = "device_tts"
        self.assertIn("tts_not_packaged", self.run_audit([rec])["blocked"][0]["reasons"])
        self.assertFalse(offline_tts_ready("voice-de-1", []))
        self.assertTrue(offline_tts_ready("voice-de-1", ["voice-de-1"]))

    def test_duplicate_audio_preserves_originals(self):
        second = json.loads(json.dumps(self.record)); second["pronunciation_id"] = "pron_de_2"
        second["variant_id"] = "regional"; second["audio"][0]["asset_id"] = "asset_2"
        result = self.run_audit([second, self.record])
        self.assertEqual(len(result["accepted"]), 2)
        self.assertEqual(result["coverage"]["de"]["audio_files"], 1)
        self.assertEqual(result["duplicates"][0]["sha256"], self.sha)
        self.assertTrue(self.wav.exists())

    def test_audio_rights_must_be_individually_evidenced(self):
        rec = json.loads(json.dumps(self.record))
        rec["audio"][0].pop("rights_evidence_sha256")
        self.assertIn("audio_license_unverified", self.run_audit([rec])["blocked"][0]["reasons"])
        rec = json.loads(json.dumps(self.record))
        rec["audio"][0]["rights_url"] = "https://example.org/other"
        self.assertIn("audio_license_unverified", self.run_audit([rec])["blocked"][0]["reasons"])
        ledger = json.loads(json.dumps(self.ledger))
        del ledger["sources"][0]["license"]["evidence_url"]
        self.assertIn("source_not_approved", self.run_audit(ledger=ledger)["blocked"][0]["reasons"])

    def test_package_is_reproducible_and_sources_remain(self):
        from tools.factory_extensions.pronunciation_scale.factory import package
        report = self.run_audit()
        first = self.root / "out1.tar"
        second = self.root / "out2.tar"
        self.assertEqual(package(report, self.root, first)["package_sha256"],
                         package(report, self.root, second)["package_sha256"])
        self.assertTrue(self.wav.is_file())
        import tarfile
        with tarfile.open(first) as archive:
            self.assertEqual(len(archive.getmembers()), 2)

    def test_cross_language_dedup_retains_each_language_coverage(self):
        other = json.loads(json.dumps(self.record))
        other.update({"pronunciation_id":"pron_ar_1", "lexeme_id":"lex_ar_1", "language_id":"ar", "language_tag":"ar", "script":"Arab"})
        other["audio"][0]["asset_id"] = "asset_ar_1"
        result = self.run_audit([self.record, other])
        self.assertEqual(result["coverage"]["ar"]["audio_files"], 1)
        self.assertEqual(result["coverage"]["de"]["audio_files"], 1)
        self.assertEqual(result["unique_file_count"], 1)

    def test_generated_audio_requires_separate_authorization(self):
        rec = json.loads(json.dumps(self.record)); rec["audio"][0]["kind"] = "licensed_generated_recording"
        self.assertIn("generation_rights_missing", self.run_audit([rec])["blocked"][0]["reasons"])
        rec["audio"][0]["generation"] = {"engine_id":"fixture_engine", "voice_id":"fixture_voice",
            "commercial_redistribution_approved":True, "terms_url":"https://example.org/terms",
            "proof_sha256":hashlib.sha256(self.license_path.read_bytes()).hexdigest(), "proof_path":"license.txt"}
        self.assertEqual(self.run_audit([rec])["coverage"]["de"]["audio_files"], 1)
        accepted = self.run_audit([rec])["accepted"][0]
        self.assertEqual(accepted["generation"]["engine_id"], "fixture_engine")
        self.assertEqual(accepted["rights_evidence_sha256"], rec["audio"][0]["rights_evidence_sha256"])


if __name__ == "__main__":
    unittest.main()
