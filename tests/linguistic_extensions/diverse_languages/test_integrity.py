"""Contract regressions: all external data below is deliberately synthetic."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[3] / "tools/linguistic_extensions/diverse_languages/audit.py"
spec = importlib.util.spec_from_file_location("diverse_audit_integrity", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class EvidenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ("catalog", "legal/ledger", "proof"):
            (self.root / directory).mkdir(parents=True)
        codes = list(audit.RESEARCH_FOCUS)
        codes += [a + b for a in "abcdefghijklmnopqrstuvwxyz" for b in "abcdefghijklmnopqrstuvwxyz"
                  if a + b not in codes][:100 - len(codes)]
        registry = [{"id": c, "display_names": {"en": c}, "native_name": c,
                     "scripts": ["Latn"], "dialects": [],
                     "morphology": {"features": [], "review_status": "provisional"}}
                    for c in codes]
        self.write("catalog/language_registry.v1.json", {"languages": registry})
        self.write("catalog/content_readiness.v1.json", {"states": dict.fromkeys(codes, "unverified")})
        self.write("legal/ledger/sources.json", {"schema_version": "1.0.0", "sources": []})
        self.write("tools/linguistic_extensions/diverse_languages/source_bindings.json",
                   {"schema_version": "1.0", "bindings": []})

    def write(self, name, payload):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def blob(self, name, value):
        path = self.root / "proof" / name
        path.write_bytes(value)
        return str(path.relative_to(self.root)), hashlib.sha256(value).hexdigest()

    def candidate(self, **changes):
        row = dict(record_id="r1", language_id="yo", lemma="ọ̀rọ̀", meaning="speech",
                   variant="yo-Latn", source_id="s1", publisher="Example source",
                   community="", speaker_consent_ref="", license="CC0-1.0",
                   rights_url="https://example.org/rights/edition-1")
        row.update(changes)
        return row

    def shard(self, rows):
        path = self.root / "candidates.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return path

    def worker(self):
        return audit.DiverseAudit(root=self.root, binding_path=self.root /
            "tools/linguistic_extensions/diverse_languages/source_bindings.json")

    def approve_synthetic_source(self, *, language="yo", variant="yo-Latn"):
        retrieval_path, retrieval_hash = self.blob("snapshot.txt", b"synthetic lexical evidence")
        license_path, license_hash = self.blob("rights.txt", b"synthetic rights proof")
        language_path, language_hash = self.blob("language.txt", b"synthetic language identity evidence")
        source = {
            "source_id": "s1", "kind": "dictionary", "origin_url": "https://example.org/dictionary",
            "publisher": "Example source", "dataset_version": "1",
            "retrieval": {"identity": "example-1", "url": "https://example.org/snapshot",
                          "date": "2026-10-13", "artifact_path": retrieval_path,
                          "sha256": retrieval_hash},
            "license": {"id": "CC0-1.0", "evidence_url": "https://example.org/rights/edition-1",
                        "evidence_path": license_path, "evidence_sha256": license_hash},
            "status": "APPROVED_FOR_REDISTRIBUTION", "alterations": ["none"],
            "review": {"reviewer": "synthetic-reviewer",
                       "decision_url": "https://example.org/reviews/approved"}
        }
        self.write("legal/ledger/sources.json", {"schema_version": "1.0.0", "sources": [source]})
        binding = {"source_id": "s1", "language_id": language, "variant": variant,
                   "proof_path": language_path, "proof_sha256": language_hash,
                   "review": {"reviewer": "synthetic-reviewer",
                              "decision_url": "https://example.org/reviews/language"}}
        self.write("tools/linguistic_extensions/diverse_languages/source_bindings.json",
                   {"schema_version": "1.0", "bindings": [binding]})

    def test_valid_canonical_ledger_and_separate_language_binding_can_be_evaluated(self):
        self.approve_synthetic_source()
        result = self.worker().audit_shard(self.shard([self.candidate()]))
        self.assertEqual(result["admissible_candidate_counts_not_published"]["yo"], 1)
        self.assertEqual(result["review_queue"], [])

    def test_neighbor_language_cannot_inherit_another_language_source(self):
        self.approve_synthetic_source()
        result = self.worker().audit_shard(self.shard([self.candidate(language_id="ig", variant="ig-Latn")]))
        self.assertEqual(result["admissible_candidate_counts_not_published"]["ig"], 0)
        self.assertIn("source_language_not_approved", result["review_queue"][0]["reasons"])

    def test_fake_ledger_with_old_unrecognized_approval_fields_fails_closed(self):
        self.write("legal/ledger/sources.json", {"schema_version": "1.0.0", "sources": [{
            "source_id": "s1", "status": "APPROVED_FOR_REDISTRIBUTION",
            "review": {"approved_by": "anyone"}, "retrieval": {"sha256": "a" * 64},
            "license": "CC0-1.0", "rights_url": "https://example.org/rights",
            "publisher": "Example source", "languages": ["yo"]}]})
        result = self.worker().audit_shard(self.shard([self.candidate()]))
        self.assertIn("redistribution_rights_unverified", result["review_queue"][0]["reasons"])

    def test_wrong_type_id_or_language_never_crashes_audit(self):
        rows = [self.candidate(record_id=["bad"]), self.candidate(language_id=["yo"]),
                self.candidate(lemma={"bad": "word"})]
        result = self.worker().audit_shard(self.shard(rows))
        self.assertEqual(result["processed"], 3)
        self.assertEqual(len(result["review_queue"]), 3)
        self.assertEqual(sum(result["admissible_candidate_counts_not_published"].values()), 0)

    def test_noun_class_is_not_german_gender_and_needs_lexeme_evidence(self):
        result = self.worker().audit_shard(self.shard([
            self.candidate(annotation={"feature": "grammatical_gender", "label": "masculine",
                                       "attested_form": "ọ̀rọ̀", "locator": "p.3"})]))
        self.assertIn("unsupported_language_feature", result["review_queue"][0]["reasons"])

    def test_language_specific_attested_annotation_requires_locator_and_surface(self):
        self.approve_synthetic_source(language="tl", variant="tl-Latn")
        rows = [
            self.candidate(language_id="tl", variant="tl-Latn",
                           annotation={"feature": "focus_voice", "label": "actor",
                                       "attested_form": "kumain", "locator": ""}),
            self.candidate(language_id="tl", variant="tl-Latn", record_id="r2",
                           annotation={"feature": "focus_voice", "label": "actor",
                                       "attested_form": "kumain", "locator": "source:line:5"})
        ]
        result = self.worker().audit_shard(self.shard(rows))
        self.assertIn("incomplete_attested_analysis", result["review_queue"][0]["reasons"])
        self.assertEqual(result["admissible_candidate_counts_not_published"]["tl"], 1)

    def test_bogus_script_and_self_asserted_consent_never_auto_approve(self):
        self.approve_synthetic_source()
        rows = [self.candidate(record_id="script", variant="yo-Hans"),
                self.candidate(record_id="rights", community="a community",
                               speaker_consent_ref="unverified-ref")]
        result = self.worker().audit_shard(self.shard(rows))
        self.assertIn("unresolved_variety_or_script", result["review_queue"][0]["reasons"])
        self.assertIn("community_or_speaker_rights_require_external_review",
                      result["review_queue"][1]["reasons"])
        self.assertEqual(sum(result["admissible_candidate_counts_not_published"].values()), 0)

    def test_missing_language_binding_proof_cannot_promote_candidate(self):
        self.approve_synthetic_source()
        binding_path = self.root / "tools/linguistic_extensions/diverse_languages/source_bindings.json"
        manifest = json.loads(binding_path.read_text(encoding="utf-8"))
        manifest["bindings"][0]["proof_sha256"] = "0" * 64
        self.write("tools/linguistic_extensions/diverse_languages/source_bindings.json", manifest)
        result = self.worker().audit_shard(self.shard([self.candidate()]))
        self.assertIn("source_language_not_approved", result["review_queue"][0]["reasons"])

    def test_tone_orthography_cannot_be_generated_from_unmarked_text(self):
        result = self.worker().audit_shard(self.shard([
            self.candidate(lemma="oro", annotation={"feature": "tone_orthography",
                "label": "high", "attested_form": "oro", "locator": "p.8"})]))
        self.assertIn("unmarked_tone_surface", result["review_queue"][0]["reasons"])

    def test_structural_wals_claims_are_not_lexical_pack_readiness(self):
        worker = audit.DiverseAudit(root=self.root)
        self.assertFalse(worker.profile("sw")["lexical_packs_verified"])
        self.assertNotIn("grammatical_gender", worker.profile("sw")["provisional_registry_features"])


if __name__ == "__main__":
    unittest.main()
