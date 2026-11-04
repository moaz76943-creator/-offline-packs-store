"""Offline tests: original revision-pinned Wikidata JSON is NOT legal approval."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.gha_factory.admission.pipeline import admit, AdmissionError
from tools.gha_factory.admission.wikidata_lexeme_adapter import parse_lexeme


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class WikidataLexemeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "legal/ledger").mkdir(parents=True)
        (self.root / "catalog").mkdir()
        (self.root / "input").mkdir()
        (self.root / "catalog/language_registry.v1.json").write_text(json.dumps({
            "schema_version": "1.0.0",
            "languages": [{"id": "de", "default_script": "Latn"}]
        }))
        self.entity = {
            "entities": {"L99": {
                "id": "L99", "lastrevid": 123, "language": "Q188",
                "lexicalCategory": "Q24905",
                "lemmas": {"de": {"value": "lernen"}},
                "forms": [{"id": "L99-F1", "representations": {"de": {"value": "lerne"}},
                           "grammaticalFeatures": ["Q110786"]}],
                "senses": [
                    {"id": "L99-S1", "claims": {"P5137": [
                        {"rank": "normal", "mainsnak": {"snaktype": "value",
                         "datavalue": {"value": {"entity-type": "item", "id": "Q11"}}}}]}},
                    {"id": "L99-S2", "claims": {"P5137": [
                        {"rank": "deprecated", "mainsnak": {"snaktype": "value",
                         "datavalue": {"value": {"entity-type": "item", "id": "Q22"}}}}]}}
                ]
            }}
        }
        self.raw = json.dumps(self.entity, ensure_ascii=False).encode()
        (self.root / "input/L99.json").write_bytes(self.raw)
        evidence = b"Wikidata Lexeme namespace: Creative Commons CC0 License.\n"
        (self.root / "input/license.txt").write_bytes(evidence)
        url = "https://www.wikidata.org/wiki/Special:EntityData/L99.json?revision=123"
        self.source = {
            "source_id": "fixture-lexeme", "kind": "dictionary",
            "origin_url": url, "publisher": "Fixture",
            "dataset_version": "L99-r123",
            "retrieval": {
                "identity": "wikidata:Lexeme:L99:revision:123", "url": url,
                "date": "2026-10-25", "artifact_path": "input/L99.json",
                "sha256": sha(self.raw),
            },
            "license": {"id": "CC0-1.0",
                        "evidence_url": "https://www.wikidata.org/wiki/Wikidata:Copyright",
                        "evidence_path": "input/license.txt", "evidence_sha256": sha(evidence)},
            "status": "APPROVED_FOR_REDISTRIBUTION",
            "alterations": ["synthetic unit-test fixture only"],
            "review": {"reviewer": "fixture-only",
                       "decision_url": "https://example.org/fixture-decision"}
        }
        self.ledger()

    def ledger(self):
        (self.root / "legal/ledger/sources.json").write_text(
            json.dumps({"schema_version": "1.0.0", "sources": [self.source]}))

    def run_adapter(self):
        return admit(repo_root=self.root, source_id="fixture-lexeme",
                     input_path=self.root / "input/L99.json",
                     out_dir=self.root / "queue", language="de",
                     dataset_version="L99-r123",
                     format_name="wikidata-lexeme-json", part_size=1)

    def test_two_attested_senses_with_no_invented_translations(self):
        result = self.run_adapter()
        self.assertEqual(result["actual_accepted_records"], 2)
        self.assertFalse(result["publication_approved"])
        self.assertFalse(result["production_ready"])
        self.assertEqual(len(result["jobs"]), 2)
        first = json.loads((self.root / "queue" / result["jobs"][0]["path"]).read_text())
        self.assertEqual(first["content"]["sense_id"], "L99-S1")
        self.assertEqual(first["content"]["concept_links"]["P5137"], ["Q11"])
        self.assertEqual(first["content"]["forms"][0]["form_id"], "L99-F1")
        self.assertEqual(first["content"]["level"], "UNKNOWN")
        self.assertEqual(first["content"]["directed_translations"], [])
        self.assertNotIn("glosses", first["content"])
        for job in result["jobs"]:
            self.assertEqual(sha((self.root / "queue" / job["path"]).read_bytes()), job["sha256"])

    def test_unapproved_source_never_creates_queue(self):
        self.source["status"] = "REVIEW_REQUIRED"
        self.ledger()
        with self.assertRaisesRegex(AdmissionError, "reviewer approval absent"):
            self.run_adapter()
        self.assertFalse((self.root / "queue").exists())

    def test_unrelated_source_or_license_cannot_masquerade_as_lexeme(self):
        for key, value in (("origin_url", "https://example.org/fake"),
                           ("license", dict(self.source["license"], id="CC-BY-SA-4.0"))):
            original = copy.deepcopy(self.source[key])
            self.source[key] = value
            self.ledger()
            with self.assertRaisesRegex(AdmissionError, "Wikidata original revision/CC0"):
                self.run_adapter()
            self.assertFalse((self.root / "queue").exists())
            self.source[key] = original

    def test_tampered_revision_language_and_duplicate_senses_fail_closed(self):
        for mutation in ("revision", "language", "duplicate"):
            bad = copy.deepcopy(self.entity)
            item = bad["entities"]["L99"]
            if mutation == "revision":
                item["lastrevid"] = 124
            elif mutation == "language":
                item["language"] = "Q1860"
            else:
                item["senses"].append(copy.deepcopy(item["senses"][0]))
            raw = json.dumps(bad).encode()
            (self.root / "input/L99.json").write_bytes(raw)
            self.source["retrieval"]["sha256"] = sha(raw)
            self.ledger()
            with self.assertRaisesRegex(AdmissionError, "REJECTED_RECORD"):
                self.run_adapter()
            self.assertFalse((self.root / "queue").exists())

    def test_original_public_pinned_lexemes_parse_without_approval(self):
        repo = Path(__file__).resolve().parents[3]
        folder = repo / "legal/ledger/evidence/wikidata-20261023"
        cases = [("de", "L1026", 2457144138, 5, 32, "Latn"),
                 ("en", "L3006", 2549891188, 19, 5, "Latn"),
                 ("ar", "L7882", 2548839684, 1, 3, "Arab")]
        for lang, lexeme, revision, senses, forms, script in cases:
            with self.subTest(language=lang):
                raw = (folder / ("%s-%s.json" % (lexeme, revision))).read_bytes()
                source = {"retrieval": {
                    "identity": "wikidata:Lexeme:%s:revision:%s" % (lexeme, revision)}}
                rows = parse_lexeme(raw, lang, source, script)
                self.assertEqual(len(rows), senses)
                self.assertEqual(len(rows[0][2]["forms"]), forms)
                self.assertTrue(all(row[2]["level"] == "UNKNOWN" for row in rows))
                self.assertTrue(all(row[2]["directed_translations"] == [] for row in rows))


if __name__ == "__main__":
    unittest.main()
