import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from registry import PronunciationRegistry


def _put(root, name, value):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return hashlib.sha256(value).hexdigest()


def _write_pronunciation_ledger(root, source_id="pronunciation-case", dataset_version="1.0", kind="pronunciation"):
    """Temporary test-only ledger. Not a production approval or a real license grant."""
    origin = "https://example.org/pronunciation-case"
    original_sha = _put(root, "evidence/upstream.bin", b"source fixture bytes")
    rights_sha = _put(root, "evidence/rights.txt", b"Test author grants CC0 to fixture data")
    source = {
        "source_id": source_id,
        "kind": kind,
        "origin_url": origin,
        "publisher": "Example Test Publisher",
        "author": "Test Author",
        "dataset_version": dataset_version,
        "retrieval": {
            "identity": "test-capture",
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
        "status": "APPROVED_FOR_REDISTRIBUTION",
        "review": {"reviewer": "fixture-reviewer", "decision_url": origin + "/review"},
        "alterations": ["no changes"],
    }
    ledger = {"schema_version": "1.0.0", "sources": [source]}
    path = Path(root) / "legal" / "ledger" / "sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger), encoding="utf-8")
    return source


class TestPronunciationMetadata(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = _write_pronunciation_ledger(self.root)
        self.schema_path = os.path.join(os.path.dirname(__file__), "pronunciation.schema.json")
        self.registry = PronunciationRegistry(self.schema_path, repo_root=self.root)

    def record(self, **overrides):
        source = {
            "source_id": self.source["source_id"],
            "dataset_version": self.source["dataset_version"],
            "publication_approved": True,
            "fixture_only": False,
        }
        source.update(overrides.pop("source", {}))
        row = {
            "lexeme_id": "test-lex-1",
            "language": "en",
            "script": "Latn",
            "locale": "en-US",
            "notation": "ipa",
            "value": "hɛˈloʊ",
            "offline_voice_support": "unknown",
            "source": source,
        }
        row.update(overrides)
        return row

    def test_valid_ipa(self):
        self.registry.add_record(self.record())
        self.assertEqual(len(self.registry.records), 1)

    def test_invalid_ipa_symbols(self):
        with self.assertRaisesRegex(ValueError, "Invalid Unicode IPA symbols detected"):
            self.registry.add_record(self.record(value="hello@123"))

    def test_newline_only_ipa_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid Unicode IPA symbols detected"):
            self.registry.add_record(self.record(value="\n"))

    def test_emoji_ipa_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid Unicode IPA symbols detected"):
            self.registry.add_record(self.record(value="hɛˈloʊ😀"))

    def test_control_character_ipa_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid Unicode IPA symbols detected"):
            self.registry.add_record(self.record(value="hɛ\u0000loʊ"))

    def test_combining_mark_ipa_accepted(self):
        self.registry.add_record(self.record(value="bɔ̃.ʒuʁ", language="fr", locale="fr-FR"))
        self.assertEqual(len(self.registry.records), 1)

    def test_dialect_and_unknown_voice(self):
        self.registry.add_record(self.record(
            language="es", locale="es-MX", dialect="Mexican Spanish", value="o.la",
        ))
        self.assertEqual(len(self.registry.records), 1)

    def test_cjk_phonetic_representation(self):
        self.registry.add_record(self.record(
            lexeme_id="test-lex-2", language="zh", script="Hans", locale="zh-CN",
            notation="romanization", value="nǐ hǎo", offline_voice_support="unsupported",
        ))
        self.assertEqual(len(self.registry.records), 1)

    def test_missing_evidence_unverified_source(self):
        row = self.record()
        del row["source"]["dataset_version"]
        with self.assertRaises(ValueError):
            self.registry.add_record(row)

    def test_dataset_version_alone_is_not_publication_evidence(self):
        row = self.record()
        row["source"] = {"source_id": "src-1", "dataset_version": "v1.0"}
        with self.assertRaisesRegex(ValueError, "approved non-fixture"):
            self.registry.add_record(row)
        self.assertEqual(self.registry.records, {})

    def test_publication_approved_false_rejected(self):
        row = self.record()
        row["source"]["publication_approved"] = False
        with self.assertRaisesRegex(ValueError, "approved non-fixture"):
            self.registry.add_record(row)

    def test_fixture_only_true_rejected(self):
        row = self.record()
        row["source"]["fixture_only"] = True
        with self.assertRaisesRegex(ValueError, "approved non-fixture"):
            self.registry.add_record(row)

    def test_missing_source_author_in_ledger_is_rejected(self):
        path = self.root / "legal" / "ledger" / "sources.json"
        ledger = json.loads(path.read_text(encoding="utf-8"))
        ledger["sources"][0].pop("author")
        path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "canonical legal ledger"):
            self.registry.add_record(self.record())

    def test_flags_without_canonical_ledger_source_rejected(self):
        row = self.record()
        row["source"]["source_id"] = "src-1"
        with self.assertRaisesRegex(ValueError, "canonical legal ledger"):
            self.registry.add_record(row)

    def test_real_repository_ledger_does_not_admit_claimed_approval(self):
        registry = PronunciationRegistry(self.schema_path)
        row = self.record()
        with self.assertRaisesRegex(ValueError, "canonical legal ledger"):
            registry.add_record(row)

    def test_stale_dataset_version_rejected(self):
        row = self.record()
        row["source"]["dataset_version"] = "v9"
        with self.assertRaisesRegex(ValueError, "canonical legal ledger"):
            self.registry.add_record(row)

    def test_dictionary_ledger_kind_cannot_back_pronunciation(self):
        root = Path(self.temp.name) / "dictionary"
        _write_pronunciation_ledger(root, kind="dictionary")
        registry = PronunciationRegistry(self.schema_path, repo_root=root)
        with self.assertRaisesRegex(ValueError, "canonical legal ledger"):
            registry.add_record(self.record())

    def test_locale_variants_do_not_overwrite(self):
        self.registry.add_record(self.record(locale="en-US"))
        self.registry.add_record(self.record(locale="en-GB"))
        self.assertEqual(len(self.registry.records), 2)
        locales = sorted(row["locale"] for row in self.registry.compile("doc-locales")["pronunciations"])
        self.assertEqual(locales, ["en-GB", "en-US"])

    def test_sense_and_script_are_identity_fields(self):
        self.registry.add_record(self.record(sense_id="sense-one"))
        self.registry.add_record(self.record(sense_id="sense-two"))
        self.registry.add_record(self.record(script="Cyrl", sense_id="sense-one"))
        self.assertEqual(len(self.registry.records), 3)

    def test_installed_without_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, "device, platform, and vetted capability"):
            self.registry.add_record(self.record(offline_voice_support="installed"))
        self.assertEqual(self.registry.records, {})

    def test_installed_blanket_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, "device, platform, and vetted capability"):
            self.registry.add_record(self.record(
                offline_voice_support="installed",
                offline_voice_scope={"device": "all", "platform": "any", "capability": "guaranteed"},
            ))

    def test_installed_with_concrete_scope_accepted(self):
        self.registry.add_record(self.record(
            offline_voice_support="installed",
            offline_voice_scope={
                "device": "pixel-7",
                "platform": "android-14",
                "capability": "en-us-compact-v3",
            },
        ))
        self.assertEqual(len(self.registry.records), 1)

    def test_auto_gen_orthography_rejected(self):
        row = self.record()
        row["source"]["source_id"] = "auto-gen-orthography"
        with self.assertRaisesRegex(ValueError, "Auto-generating pronunciation from orthographic spelling is not allowed"):
            self.registry.add_record(row)

    def test_deterministic_output_and_incremental(self):
        record1 = self.record(lexeme_id="lex-1", locale="en-US", value="hɛˈloʊ")
        record2 = self.record(
            lexeme_id="lex-2", language="fr", locale="fr-FR", value="bɔ̃.ʒuʁ",
            offline_voice_support="installed",
            offline_voice_scope={
                "device": "pixel-7",
                "platform": "android-14",
                "capability": "fr-fr-compact-v1",
            },
        )
        self.registry.add_record(record2)
        self.registry.add_record(record1)
        self.registry.add_record(record1)
        self.assertEqual(len(self.registry.records), 2)
        doc = self.registry.compile("doc-1")
        self.assertEqual(doc["pronunciations"][0]["language"], "en")
        self.assertEqual(doc["pronunciations"][1]["language"], "fr")

    def test_wrong_language_format(self):
        with self.assertRaises(ValueError):
            self.registry.add_record(self.record(language="English"))

    def test_rejected_source_is_not_exported(self):
        self.registry.add_record(self.record())
        bad = self.record(lexeme_id="test-lex-9")
        bad["source"]["fixture_only"] = True
        with self.assertRaises(ValueError):
            self.registry.add_record(bad)
        out = self.root / "registry.json"
        self.registry.export_json("doc-export", str(out))
        exported = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([row["lexeme_id"] for row in exported["pronunciations"]], ["test-lex-1"])


if __name__ == "__main__":
    unittest.main()
