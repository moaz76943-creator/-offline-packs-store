"""Synthetic-only tests: do not treat these records as approved morphology."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.linguistic_extensions.european_inflection.validator import (
    ContractError, PROFILES, validate_record, validate_profiles, process_shards,
    source_gate, sha256_file,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = {
    "test-source": {
        "source_id": "test-source",
        "kind": "morphology",
        "status": "APPROVED_FOR_REDISTRIBUTION",
        "dataset_version": "synthetic-1",
        "retrieval": {"sha256": "a" * 64},
    },
    "test-second": {
        "source_id": "test-second",
        "kind": "morphology",
        "status": "APPROVED_FOR_REDISTRIBUTION",
        "dataset_version": "synthetic-1",
        "retrieval": {"sha256": "b" * 64},
    },
}

def record(lang="ru", script="Cyrl", form="тест", features=None, status="verified"):
    return {
        "record_id": lang + ":record:synthetic-1",
        "language_code": lang,
        "lemma_id": lang + ":lemma:synthetic-1",
        "sense_id": lang + ":sense:synthetic-1",
        "lemma": form,
        "form": form,
        "script": script,
        "category": "noun",
        "features": features or {"case": "nominative"},
        "evidence_status": status,
        "paradigm_complete": False,
        "source_refs": [{
            "source_id": "test-source", "dataset_version": "synthetic-1",
            "artifact_sha256": "a" * 64, "locator": "synthetic:test:1"
        }]
    }

class ContractTests(unittest.TestCase):
    def test_profiles_exactly_match_registered_languages_and_scripts(self):
        self.assertEqual(len(PROFILES), 19)
        validate_profiles(ROOT)

    def test_evidence_is_accepted_without_inference(self):
        self.assertEqual(validate_record(record(), SOURCE)["form"], "тест")

    def test_contrastive_negative_fixtures(self):
        fixtures = json.loads((HERE / "contrastive_negative.json").read_text(encoding="utf-8"))
        for case in fixtures:
            with self.subTest(name=case["name"]):
                r = record(**case.get("base", {}))
                r.update(case.get("set", {}))
                if case.get("feature_set"):
                    r["features"] = case["feature_set"]
                with self.assertRaises(ContractError):
                    validate_record(r, SOURCE)

    def test_slovenian_dual_is_not_croatian_dual(self):
        sl = record("sl", "Latn", "test", {"number": "dual"})
        self.assertEqual(validate_record(sl, SOURCE)["language_code"], "sl")
        hr = record("hr", "Latn", "test", {"number": "dual"})
        with self.assertRaises(ContractError):
            validate_record(hr, SOURCE)

    def test_celtic_mutation_requires_attested_trigger(self):
        ga = record("ga", "Latn", "teach", {"mutation": "lenition"})
        with self.assertRaises(ContractError):
            validate_record(ga, SOURCE)
        ga["features"]["mutation_trigger"] = "synthetic-context"
        self.assertEqual(validate_record(ga, SOURCE)["features"]["mutation"], "lenition")

    def test_disagreement_requires_two_independent_sources(self):
        x = record(status="disagreement")
        x["disagreement_note"] = "synthetic conflict"
        with self.assertRaises(ContractError):
            validate_record(x, SOURCE)
        x["source_refs"].append({
            "source_id": "test-second", "dataset_version": "synthetic-1",
            "artifact_sha256": "b" * 64, "locator": "synthetic:test:2"
        })
        self.assertEqual(validate_record(x, SOURCE)["evidence_status"], "disagreement")

    def test_greek_accents_are_not_stripped(self):
        x = record("el", "Grek", "λόγος", {"case": "nominative", "accent": "marked"})
        self.assertEqual(validate_record(x, SOURCE)["form"], "λόγος")
        x["form"] = "λογος"
        with self.assertRaises(ContractError):
            validate_record(x, SOURCE)

    def test_only_admitted_sources_pass_source_gate(self):
        self.assertEqual(source_gate("test-source", "synthetic-1", "a" * 64, SOURCE), None)
        with self.assertRaises(ContractError):
            source_gate("test-source", "wrong", "a" * 64, SOURCE)
        with self.assertRaises(ContractError):
            source_gate("unlisted", "synthetic-1", "a" * 64, SOURCE)

    def test_production_has_zero_sources_no_claims(self):
        with tempfile.TemporaryDirectory() as td:
            result = process_shards(ROOT, Path(td) / "no_shards", Path(td) / "output")
            self.assertEqual(result["status"], "BLOCKED_NO_ADMITTED_SHARDS")
            self.assertEqual(result["total"], 0)
            self.assertEqual(result["languages"]["ru"]["verified"], 0)

    def test_nfc_and_duplicate_fields_rejected(self):
        from tools.linguistic_extensions.european_inflection.validator import loads_unique
        with self.assertRaises(ContractError):
            loads_unique('{"a":1,"a":2}')
        x = record()
        x["form"] = "е\u0301"
        with self.assertRaises(ContractError):
            validate_record(x, SOURCE)

    def test_predictions_and_gaps_never_emit_verified_output(self):
        from tools.linguistic_extensions.european_inflection.validator import summarize
        rows = [record(status="predicted"), record(status="gap")]
        rows[0]["prediction_note"] = "synthetic-only"
        rows[1]["gap_note"] = "synthetic-only"
        report = summarize(rows, SOURCE)
        self.assertEqual(report["verified"], [])
        self.assertEqual(report["counts"]["predicted"], 1)
        self.assertEqual(report["counts"]["gap"], 1)


    def test_immutable_shard_streams_attested_and_quarantined_separately(self):
        from unittest.mock import patch
        from tools.linguistic_extensions.european_inflection import validator as engine
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shards = root / "tools/linguistic_extensions/european_inflection/shards"
            shards.mkdir(parents=True)
            a = record()
            b = record("sl", "Latn", "test", {"number": "dual"}, "predicted")
            b["prediction_note"] = "synthetic quarantine"
            payload = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in (a, b))
            digest = __import__("hashlib").sha256(payload.encode("utf-8")).hexdigest()
            (shards / (digest + ".jsonl")).write_text(payload, encoding="utf-8")
            output = root / "output"
            with patch.object(engine, "validate_profiles", return_value=True), patch.object(
                    engine, "_load_admission", return_value=SOURCE):
                result = process_shards(root, shards, output)
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["languages"]["ru"]["verified"], 1)
            self.assertEqual(result["languages"]["sl"]["predicted"], 1)
            self.assertEqual(len(list(output.glob("*.verified.jsonl"))), 1)
            self.assertEqual(len(list(output.glob("*.predicted.jsonl"))), 1)
            verified_text = next(output.glob("*.verified.jsonl")).read_text(encoding="utf-8")
            self.assertNotIn("synthetic quarantine", verified_text)

    def test_shard_name_must_match_immutable_sha(self):
        from unittest.mock import patch
        from tools.linguistic_extensions.european_inflection import validator as engine
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shards = root / "tools/linguistic_extensions/european_inflection/shards"
            shards.mkdir(parents=True)
            (shards / "mutable.jsonl").write_text(json.dumps(record(), ensure_ascii=False) + "\n", encoding="utf-8")
            with patch.object(engine, "validate_profiles", return_value=True), patch.object(
                    engine, "_load_admission", return_value=SOURCE):
                with self.assertRaises(ContractError):
                    process_shards(root, shards, root / "out")


    def test_atomic_run_rejects_later_bad_shard_without_partial_publish(self):
        from hashlib import sha256
        from unittest.mock import patch
        from tools.linguistic_extensions.european_inflection import validator as engine
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shards = root / "tools/linguistic_extensions/european_inflection/shards"
            shards.mkdir(parents=True)
            good = (json.dumps(record(), ensure_ascii=False) + "\n").encode("utf-8")
            # Deliberately sort first by digest: a first valid shard, then invalid.
            invalid = b'{"record_id": "ru:bad", "language_code":"ru"}\n'
            for raw in (good, invalid):
                name = sha256(raw).hexdigest() + ".jsonl"
                (shards / name).write_bytes(raw)
            output = root / "out"
            with patch.object(engine, "validate_profiles", return_value=True), patch.object(
                    engine, "_load_admission", return_value=SOURCE):
                with self.assertRaises(ContractError):
                    process_shards(root, shards, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".european-inflection-*")), [])

    def test_immutable_output_never_overwrites_an_existing_run(self):
        from unittest.mock import patch
        from tools.linguistic_extensions.european_inflection import validator as engine
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shards = root / "tools/linguistic_extensions/european_inflection/shards"
            shards.mkdir(parents=True)
            from hashlib import sha256
            payload = (json.dumps(record(), ensure_ascii=False) + "\n").encode("utf-8")
            (shards / (sha256(payload).hexdigest() + ".jsonl")).write_bytes(payload)
            output = root / "out"
            with patch.object(engine, "validate_profiles", return_value=True), patch.object(
                    engine, "_load_admission", return_value=SOURCE):
                process_shards(root, shards, output)
                before = (output / "summary.json").read_bytes()
                with self.assertRaises(ContractError):
                    process_shards(root, shards, output)
                self.assertEqual((output / "summary.json").read_bytes(), before)

if __name__ == "__main__":
    unittest.main()
