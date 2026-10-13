import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/linguistic_extensions/germanic_romance"))
from engine import EvidenceEngine, EvidenceError


class MorphologyContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "catalog").mkdir()
        (self.root / "legal/ledger").mkdir(parents=True)
        profiles = json.loads(
            (ROOT / "tools/linguistic_extensions/germanic_romance/profiles.json").read_text(encoding="utf-8")
        )["languages"]
        languages = [{"id": code, "family": p["registry_family"]} for code, p in profiles.items()]
        languages += [{"id": f"zz{i}", "family": "Other"} for i in range(81)]
        (self.root / "catalog/language_registry.v1.json").write_text(json.dumps({"languages": languages}))
        (self.root / "legal/ledger/sources.json").write_text(
            json.dumps({"schema_version": "1.0.0", "sources": []}))
        self.engine = EvidenceEngine(self.root)
        self.record = dict(
            language_code="de", lemma_id="de:gehen:1", sense_id="de:gehen:move",
            lemma="gehen", form="gegangen", pos="verb",
            features={"verb_form": "past_participle"}, source_id="verified-de",
            source_version="v1", source_sha256="x" * 64, evidence_version="2026-10-13",
            record_locator="line:1")

    def approve_synthetic(self):
        # Isolated synthetic fixture, never real production approval.
        (self.root / "original.dat").write_bytes(b"synthetic source")
        (self.root / "notice.txt").write_text("synthetic source-specific license proof")
        digest = lambda p: hashlib.sha256((self.root / p).read_bytes()).hexdigest()
        self.record["source_sha256"] = digest("original.dat")
        source = {
            "source_id": "verified-de", "kind": "morphology",
            "status": "APPROVED_FOR_REDISTRIBUTION",
            "origin_url": "https://example.org/synthetic", "publisher": "fixture",
            "dataset_version": "v1", "alterations": ["none"],
            "review": {"reviewer": "fixture", "decision_url": "https://example.org/review"},
            "retrieval": {
                "identity": "fixture-v1", "url": "https://example.org/fake-dataset",
                "date": "2026-10-13", "artifact_path": "original.dat",
                "sha256": digest("original.dat")
            },
            "license": {
                "id": "CC0-1.0", "evidence_url": "https://example.org/source-license",
                "evidence_path": "notice.txt", "evidence_sha256": digest("notice.txt")
            }
        }
        (self.root / "legal/ledger/sources.json").write_text(
            json.dumps({"schema_version": "1.0.0", "sources": [source]}))
        self.engine = EvidenceEngine(self.root)

    def forms(self, *records):
        (self.root / "forms.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8")
        return "forms.jsonl"

    def test_all_19_profiles_are_independent_and_attested_only(self):
        self.assertEqual(19, len(self.engine.profiles))
        self.assertEqual("attested_only", self.engine.profiles["ro"]["generation"])
        self.assertIn("genitive_dative", self.engine.profiles["ro"]["axes"]["case"])
        self.assertNotIn("case", self.engine.profiles["en"]["axes"])
        self.assertNotIn("supine", self.engine.profiles["da"]["axes"]["verb_form"])
        self.assertIn("supine", self.engine.profiles["sv"]["axes"]["verb_form"])
        self.assertIn("personal_infinitive", self.engine.profiles["pt"]["axes"]["verb_form"])

    def test_unapproved_sources_are_not_a_verified_inventory(self):
        result = self.engine.audit("de")
        for key in ("verified_verbs", "verified_paradigms",
                    "verified_nouns", "verified_inflections"):
            self.assertEqual(0, result[key])
        self.assertFalse(self.engine.eligible_source("wiktionary-de-gehen"))

    def test_language_scope_and_feature_isolation(self):
        self.approve_synthetic()
        for bad in (dict(self.record, language_code="fr"),
                    dict(self.record, lemma_id="en:gehen:1"),
                    dict(self.record, sense_id="fr:gehen:move"),
                    dict(self.record, features={"clitic_position": "proclitic"})):
            with self.assertRaises(EvidenceError):
                self.engine.validate(bad, "de")

    def test_unicode_originals_and_real_count_semantics(self):
        self.approve_synthetic()
        verb = dict(self.record, lemma="größen", form="gegrößt")
        noun = dict(self.record, lemma_id="de:Buch:1", sense_id="de:Buch:book",
                    lemma="Buch", form="Bücher", pos="noun",
                    features={"number": "plural"})
        actual = self.engine.audit("de", self.forms(verb, noun))
        self.assertEqual((1, 1, 1, 2), tuple(actual[k] for k in
                         ("verified_verbs", "verified_paradigms",
                          "verified_nouns", "verified_inflections")))
        self.assertEqual("Bücher", self.engine.validate(noun, "de")["form"])

    def test_changed_source_artifact_fails_closed(self):
        self.approve_synthetic()
        (self.root / "original.dat").write_bytes(b"tampered")
        self.assertFalse(EvidenceEngine(self.root).eligible_source("verified-de"))
        with self.assertRaises(EvidenceError):
            EvidenceEngine(self.root).audit("de", self.forms(self.record))

    def test_participle_conflict_requires_variant_and_attestation(self):
        self.approve_synthetic()
        with self.assertRaisesRegex(EvidenceError, "conflicting"):
            self.engine.audit("de", self.forms(self.record,
                              dict(self.record, form="ging")))

    def test_uncertainty_and_compound_auxiliary_guard(self):
        self.approve_synthetic()
        with self.assertRaises(EvidenceError):
            self.engine.validate(dict(self.record, uncertainty="unresolved"), "de")
        with self.assertRaises(EvidenceError):
            self.engine.validate(dict(self.record, features={"tense": "perfect"}), "de")

    def test_sha_version_and_record_bounds(self):
        self.approve_synthetic()
        with self.assertRaises(EvidenceError):
            self.engine.validate(dict(self.record, source_sha256="0" * 64), "de")
        with self.assertRaisesRegex(EvidenceError, "bounded"):
            self.engine.audit("de", self.forms(self.record, self.record), limit=1)

    def test_no_cross_language_leak_on_equal_surface(self):
        self.approve_synthetic()
        self.engine.audit("de", self.forms(self.record))
        with self.assertRaises(EvidenceError):
            self.engine.audit("fr", "forms.jsonl")
        self.assertEqual(0, self.engine.audit("fr")["verified_inflections"])

    def test_variety_required_for_umbrella_ids(self):
        self.approve_synthetic()
        value = dict(self.record, language_code="no", lemma_id="no:gaa:1",
                     sense_id="no:gaa:move")
        with self.assertRaisesRegex(EvidenceError, "variety"):
            self.engine.validate(value, "no")

    def test_path_traversal_rejected(self):
        with self.assertRaises(EvidenceError):
            self.engine.audit("de", "../secret.jsonl")


if __name__ == "__main__":
    unittest.main()
