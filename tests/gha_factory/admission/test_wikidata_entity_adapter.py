"""Route 05-gated Wikidata JSON handoff; only synthetic approval fixtures."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.gha_factory.admission.pipeline import AdmissionError, admit
from tools.gha_factory.admission.wikidata_entity_adapter import extract_entity

ROOT = Path(__file__).resolve().parents[3]
DOSSIER = ROOT / "legal/ledger/evidence/wikidata-20261023"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class WikidataAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ("input", "catalog", "legal/ledger"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "catalog/language_registry.v1.json").write_text(json.dumps({
            "schema_version": "1.0.0",
            "languages": [{"id": "de", "default_script": "Latn"}],
        }))
        (self.root / "catalog/production_languages.v1.json").write_text(json.dumps({
            "languages": [{"id": "de", "wikidata": "Q188"}],
        }))
        (self.root / "catalog/sections.v1.json").write_text(json.dumps({
            "pos": {"Q24905": "verb"},
        }))
        self.document = {"entities": {"L1": {
            "id": "L1", "type": "lexeme", "lastrevid": 42,
            "language": "Q188", "lexicalCategory": "Q24905",
            "lemmas": {"de": {"language": "de", "value": "gehen"}},
            "senses": [{"id": "L1-S1", "glosses": {
                "de": {"language": "de", "value": "sich fortbewegen"},
            }}],
            "forms": [{"id": "L1-F1", "representations": {
                "de": {"language": "de", "value": "geht"},
            }, "grammaticalFeatures": ["Q110786"]}],
        }}}
        self.license = b"Publisher states original dataset is CC0 1.0; synthetic fixture only.\n"
        (self.root / "input/license.txt").write_bytes(self.license)
        self.source = {
            "source_id": "fixture-wikidata-l1", "kind": "dictionary",
            "origin_url": "https://www.wikidata.org/wiki/Special:EntityData/L1.json?revision=42",
            "publisher": "Synthetic fixture only", "dataset_version": "l1-r42",
            "retrieval": {"identity": "wikidata:Lexeme:L1:revision:42",
                          "url": "https://www.wikidata.org/wiki/Special:EntityData/L1.json?revision=42",
                          "date": "2026-10-24", "artifact_path": "input/lexeme.json",
                          "sha256": ""},
            "license": {"id": "CC0-1.0", "evidence_url": "https://www.wikidata.org/wiki/Wikidata:Copyright",
                        "evidence_path": "input/license.txt",
                        "evidence_sha256": sha(self.license)},
            "status": "APPROVED_FOR_REDISTRIBUTION",
            "alterations": ["none"], "review": {
                "reviewer": "synthetic-test-reviewer",
                "decision_url": "https://example.org/synthetic-decision",
            },
        }
        self.save()

    def save(self):
        raw = (json.dumps(self.document, ensure_ascii=False) + "\n").encode()
        (self.root / "input/lexeme.json").write_bytes(raw)
        self.source["retrieval"]["sha256"] = sha(raw)
        (self.root / "legal/ledger/sources.json").write_text(json.dumps({
            "schema_version": "1.0.0", "sources": [self.source],
        }))
        return raw

    def admit(self):
        return admit(repo_root=self.root, source_id=self.source["source_id"],
                     input_path=self.root / "input/lexeme.json", out_dir=self.root / "out",
                     language="de", dataset_version="l1-r42",
                     format_name="wikidata-entity-json", part_size=1)

    def test_approved_synthetic_entity_reaches_candidate_queue_not_publication(self):
        report = self.admit()
        self.assertEqual(report["actual_accepted_records"], 1)
        self.assertEqual(report["status"], "ACCEPTED_FOR_QUEUE")
        self.assertIs(report["publication_approved"], False)
        job = report["jobs"][0]
        self.assertEqual(job["record_count"], 1)
        payload = (self.root / "out" / job["path"]).read_bytes()
        self.assertEqual(sha(payload), job["sha256"])
        row = json.loads(payload)
        content = row["content"]
        self.assertEqual(content["lexeme_id"], "L1")
        self.assertEqual(content["senses"][0]["sense_id"], "L1-S1")
        self.assertEqual(content["forms"][0]["form_id"], "L1-F1")
        self.assertEqual(content["level"], "UNKNOWN")
        self.assertEqual(content["directed_translations"], [])
        self.assertEqual(content["examples"], [])
        self.assertEqual(row["source_line_sha256"], self.source["retrieval"]["sha256"])

    def test_real_three_originals_are_parsed_without_legal_admission(self):
        proposed = json.loads((DOSSIER / "proposed-sources.json").read_text())
        expected = {"de": (5, 32), "en": (19, 5), "ar": (1, 3)}
        for source in proposed["sources"]:
            lang = source["retrieval"]["identity"]
            raw = (ROOT / source["retrieval"]["artifact_path"]).read_bytes()
            self.assertEqual(sha(raw), source["retrieval"]["sha256"])
            registry = json.loads((ROOT / "catalog/production_languages.v1.json").read_text())
            entities = json.loads(raw)["entities"]
            lexeme = next(iter(entities.values()))
            language = next(row["id"] for row in registry["languages"]
                            if row["wikidata"] == lexeme["language"])
            with self.subTest(language=language):
                content, _ = extract_entity(raw, language=language,
                                            source=source, repo_root=ROOT)
                self.assertEqual((len(content["senses"]), len(content["forms"])), expected[language])
                self.assertEqual(content["directed_translations"], [])
                self.assertEqual(content["level"], "UNKNOWN")
        self.assertEqual(set(expected), {"de", "en", "ar"})

    def test_review_required_source_cannot_enter_queue(self):
        self.source["status"] = "REVIEW_REQUIRED"
        self.save()
        with self.assertRaisesRegex(AdmissionError, "reviewer approval absent"):
            self.admit()
        self.assertFalse((self.root / "out").exists())

    def test_non_cc0_and_changed_revision_rejected(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        self.save()
        with self.assertRaisesRegex(AdmissionError, "requires CC0"):
            self.admit()
        self.source["license"]["id"] = "CC0-1.0"
        self.document["entities"]["L1"]["lastrevid"] = 43
        self.save()
        with self.assertRaisesRegex(AdmissionError, "unpinned"):
            self.admit()
        self.assertFalse((self.root / "out").exists())

    def test_wrong_language_duplicate_keys_and_oversize_rejected(self):
        self.document["entities"]["L1"]["language"] = "Q1860"
        raw = self.save()
        with self.assertRaisesRegex(AdmissionError, "language or POS"):
            self.admit()
        self.document["entities"]["L1"]["language"] = "Q188"
        raw = self.save()
        bad = raw.replace(b'"entities":', b'"entities": {}, "entities":', 1)
        with self.assertRaisesRegex(AdmissionError, "duplicate JSON"):
            extract_entity(bad, language="de", source=self.source, repo_root=self.root)
        from tools.gha_factory.admission.wikidata_entity_adapter import MAX_ENTITY_BYTES
        with self.assertRaisesRegex(AdmissionError, "oversized"):
            extract_entity(b"x" * (MAX_ENTITY_BYTES + 1), language="de",
                           source=self.source, repo_root=self.root)
        self.assertFalse((self.root / "out").exists())


if __name__ == "__main__":
    unittest.main()
