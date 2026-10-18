"""Synthetic evidence fixtures; never represent published recordings."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave

from tools.factory_extensions.pronunciation_scale.factory import (
    AUDIO_LIMIT, EVIDENCE_LIMIT, admit_package, audit, offline_tts_ready, package,
)


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
        self.ledger = {"schema_version": "1.0.0", "sources": [{
            "source_id": "synthetic_source", "kind": "pronunciation", "status": "APPROVED_FOR_REDISTRIBUTION",
            "publisher": "Synthetic publisher", "dataset_version": "v1",
            "origin_url": "https://example.org/original", "review": {"reviewer": "Fixture", "decision_url": "https://example.org/review"},
            "retrieval": {"identity": "fixture-snapshot-v1", "url": "https://example.org/original", "date": "2026-10-12",
                          "artifact_path": "source.txt", "sha256": hashlib.sha256(self.source_path.read_bytes()).hexdigest()},
            "license": {"id": "CC0-1.0", "evidence_url": "https://example.org/rights", "evidence_path": "license.txt",
                        "evidence_sha256": hashlib.sha256(self.license_path.read_bytes()).hexdigest()},
            "alterations": ["none"],
        }]}
        self.lexical = {
            "lexemes": {"lex_de_1": "de", "lex_ar_1": "ar", "lex_zh_1": "zh"},
            "senses": {"sense_de_1": "lex_de_1", "sense_ar_1": "lex_ar_1", "sense_zh_1": "lex_zh_1"},
        }
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

    def run_audit(self, records=None, ledger=None, lexical=None, generated_rights=None):
        return audit(self.catalog, self.ledger if ledger is None else ledger,
                     {"metadata_version": "1.0.0", "records": [self.record] if records is None else records},
                     self.root, self.root, self.lexical if lexical is None else lexical, generated_rights)

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
        rec.update({"language_id":"zh", "language_tag":"zh-Hans-CN", "script":"Hans", "variant_id":"reading2",
                    "lexeme_id":"lex_zh_1", "sense_id":"sense_zh_1"})
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
        other.update({"pronunciation_id":"pron_ar_1", "lexeme_id":"lex_ar_1", "sense_id":"sense_ar_1",
                      "language_id":"ar", "language_tag":"ar", "script":"Arab"})
        other["audio"][0]["asset_id"] = "asset_ar_1"
        result = self.run_audit([self.record, other])
        self.assertEqual(result["coverage"]["ar"]["audio_files"], 1)
        self.assertEqual(result["coverage"]["de"]["audio_files"], 1)
        self.assertEqual(result["unique_file_count"], 1)

    def _reviewed_voice(self, **overrides):
        row = {"engine_id": "fixture_engine", "voice_id": "fixture_voice", "redistribution_permitted": True,
               "terms_url": "https://example.org/engine-voice-terms",
               "review": {"reviewer": "independent-fixture", "decision_url": "https://example.org/voice-review"}}
        row.update(overrides)
        return {"rights": [row]}

    def test_generated_audio_requires_separate_authorization(self):
        rec = json.loads(json.dumps(self.record)); rec["audio"][0]["kind"] = "licensed_generated_recording"
        self.assertIn("generation_rights_missing", self.run_audit([rec])["blocked"][0]["reasons"])
        rec["audio"][0]["generation"] = {"engine_id":"fixture_engine", "voice_id":"fixture_voice",
            "commercial_redistribution_approved": True, "terms_url": "https://example.org/terms",
            "proof_sha256": hashlib.sha256(self.license_path.read_bytes()).hexdigest(), "proof_path": "license.txt"}
        self.assertIn("generation_rights_missing", self.run_audit([rec])["blocked"][0]["reasons"])
        rec["audio"][0]["generation"]["terms_url"] = "https://example.org/engine-voice-terms"
        rec["audio"][0]["generation"]["commercial_redistribution_approved"] = False
        accepted = self.run_audit([rec], generated_rights=self._reviewed_voice())["accepted"]
        self.assertEqual(accepted[0]["generation"]["engine_id"], "fixture_engine")
        generic = self._reviewed_voice(terms_url="https://creativecommons.org/licenses/by/4.0/")
        rec["audio"][0]["generation"]["terms_url"] = generic["rights"][0]["terms_url"]
        self.assertIn("generation_rights_missing", self.run_audit([rec], generated_rights=generic)["blocked"][0]["reasons"])
        unreviewed = self._reviewed_voice()
        del unreviewed["rights"][0]["review"]
        rec["audio"][0]["generation"]["terms_url"] = "https://example.org/engine-voice-terms"
        self.assertIn("generation_rights_missing", self.run_audit([rec], generated_rights=unreviewed)["blocked"][0]["reasons"])

    def test_route05_label_without_retrieval_or_specific_terms_is_blocked(self):
        for mutation in (
            lambda src: src["retrieval"].pop("identity"),
            lambda src: src["retrieval"].pop("url"),
            lambda src: src["retrieval"].pop("date"),
            lambda src: src.pop("alterations"),
            lambda src: src["license"].__setitem__("evidence_url", "https://creativecommons.org/licenses/by-sa/4.0/"),
            lambda src: src["license"].__setitem__("evidence_url", "https://www.gnu.org/licenses/fdl-1.3.html"),
        ):
            with self.subTest(mutation=mutation):
                ledger = json.loads(json.dumps(self.ledger))
                mutation(ledger["sources"][0])
                self.assertIn("source_not_approved", self.run_audit(ledger=ledger)["blocked"][0]["reasons"])

    def test_fabricated_lexeme_or_sense_is_not_counted(self):
        rec = json.loads(json.dumps(self.record)); rec["lexeme_id"] = "lex_fabricated"
        result = self.run_audit([rec])
        self.assertIn("lexical_identity_unverified", result["blocked"][0]["reasons"])
        self.assertEqual(result["coverage"]["de"]["pronunciation_variants"], 0)
        self.assertEqual(result["coverage"]["de"]["audio_files"], 0)
        self.assertEqual(result["accepted"], [])
        rec = json.loads(json.dumps(self.record)); rec["sense_id"] = "sense_fabricated"
        self.assertIn("lexical_identity_unverified", self.run_audit([rec])["blocked"][0]["reasons"])
        rec = json.loads(json.dumps(self.record)); rec["sense_id"] = "sense_ar_1"
        self.assertIn("lexical_identity_unverified", self.run_audit([rec])["blocked"][0]["reasons"])

    def test_rights_snapshot_is_not_capped_at_audio_limit(self):
        self.assertGreater(EVIDENCE_LIMIT, AUDIO_LIMIT)
        big = self.root / "rights-large.txt"
        big.write_bytes(b"R" * (AUDIO_LIMIT + 1))
        digest = hashlib.sha256(big.read_bytes()).hexdigest()
        ledger = json.loads(json.dumps(self.ledger))
        ledger["sources"][0]["license"]["evidence_path"] = "rights-large.txt"
        ledger["sources"][0]["license"]["evidence_sha256"] = digest
        result = self.run_audit(ledger=ledger)
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["accepted"][0]["asset_id"], "asset_1")
        huge = self.root / "rights-huge.txt"
        huge.write_bytes(b"H" * (EVIDENCE_LIMIT + 1))
        ledger["sources"][0]["license"]["evidence_path"] = "rights-huge.txt"
        ledger["sources"][0]["license"]["evidence_sha256"] = hashlib.sha256(huge.read_bytes()).hexdigest()
        self.assertIn("source_not_approved", self.run_audit(ledger=ledger)["blocked"][0]["reasons"])

    def _daily_candidate(self, digest, **overrides):
        notice = self.root / "notice.txt"
        notice.write_text("synthetic_source Synthetic publisher CC0-1.0 https://example.org/original\n", encoding="utf-8")
        candidate = {
            "asset_id": "fixture-pronunciation", "kind": "pronunciation",
            "artifact_path": "packaged/audio.tar", "sha256": digest,
            "source_refs": [{"source_id": "synthetic_source", "dataset_version": "v1",
                             "artifact_sha256": self.ledger["sources"][0]["retrieval"]["sha256"]}],
            "output_license_id": "CC0-1.0", "compiler_license_id": "MIT",
            "notices": {"synthetic_source": "notice.txt"}, "compliance": {},
            "provenance_mode": "per_record",
            "record_sources": [{"record_id": "pron_de_1", "source_ids": ["synthetic_source"]}],
            "review": {"reviewer": "fixture-reviewer", "decision_url": "https://example.org/review/candidate"},
        }
        candidate.update(overrides)
        return {"schema_version": "1.0.0", "date": "2026-10-18", "release_candidates": [candidate]}

    def test_audio_tar_requires_admitted_daily_candidate(self):
        report = self.run_audit()
        destination = self.root / "qa" / "audio.tar"
        self.assertFalse(admit_package(report, self.root, destination, self.ledger, [], self.root))
        self.assertFalse(destination.exists())
        staged = self.root / "rebuild.tar"
        digest = package(report, self.root, staged)["package_sha256"]
        unreviewed = self._daily_candidate(digest)
        del unreviewed["release_candidates"][0]["review"]
        self.assertFalse(admit_package(report, self.root, destination, self.ledger, [unreviewed], self.root))
        self.assertFalse(destination.exists())
        admitted = self._daily_candidate(digest)
        self.assertTrue(admit_package(report, self.root, destination, self.ledger, [admitted], self.root))
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
