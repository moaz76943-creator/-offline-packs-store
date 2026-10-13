"""Evidence-gated diverse-language regression tests: synthetic data only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[3] / "tools/linguistic_extensions/diverse_languages/audit.py"
spec = importlib.util.spec_from_file_location("diverse_audit", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class DiverseAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for p in ("catalog", "legal/ledger"):
            (self.root / p).mkdir(parents=True)
        self.codes = list(audit.RESEARCH_FOCUS)
        self.codes += [a + b for a in "abcdefghijklmnopqrstuvwxyz" for b in "abcdefghijklmnopqrstuvwxyz"
                       if a + b not in audit.RESEARCH_FOCUS][:100 - len(self.codes)]
        languages = [{"id": c, "display_names": {"en": c}, "native_name": c,
                      "scripts": ["Latn"], "dialects": [],
                      "morphology": {"features": [], "review_status": "provisional"}}
                     for c in self.codes]
        self.write_json("catalog/language_registry.v1.json", {"languages": languages})
        self.write_json("catalog/content_readiness.v1.json", {"states": dict.fromkeys(self.codes, "unverified")})
        self.write_json("legal/ledger/sources.json", {"schema_version": "1.0.0", "sources": []})
        self.worker = audit.DiverseAudit(root=self.root)

    def write_json(self, path, value):
        (self.root / path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def candidate(self, **overrides):
        item = {"record_id": "r1", "language_id": "yo", "lemma": "ọ̀rọ̀", "meaning": "speech",
                "variant": "yo-Latn", "source_id": "fake_source", "publisher": "publisher",
                "community": "", "speaker_consent_ref": "", "license": "CC BY 4.0",
                "rights_url": "https://example.org/rights"}
        item.update(overrides)
        return item

    def rows(self, items):
        path = self.root / "candidate.jsonl"
        path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")
        return path

    def test_independent_profiles_and_registered_id_fence(self):
        self.assertEqual(len(audit.RESEARCH_FOCUS), 14)
        self.assertNotEqual(self.worker.profile("id"), self.worker.profile("ms"))
        self.assertNotEqual(self.worker.profile("zu"), self.worker.profile("xh"))
        with self.assertRaises(audit.EvidenceError):
            self.worker.profile("fil")
        with self.assertRaises(audit.EvidenceError):
            self.worker.profile("en")

    def test_verified_wals_tone_is_not_spelling_or_generated_tone_marks(self):
        fact = self.worker.profile("yo")["verified_structural_facts"][0]
        self.assertEqual((fact["dimension"], fact["value"]), ("tone", "complex_tone_system"))
        self.assertEqual(fact["source"]["speaker_or_community_consent"], "not_asserted")
        self.assertFalse(self.worker.profile("yo")["lexical_packs_verified"])

    def test_noun_classes_not_inferred_as_german_gender(self):
        self.assertIn("noun_class_inventory", self.worker.profile("sw")["research_focus_not_verified"])
        self.assertNotIn("grammatical_gender", self.worker.profile("sw")["provisional_registry_features"])
        self.assertEqual(self.worker.report()["reports"]["sw"]["verified_lexemes_in_production"], 0)

    def test_missing_ledger_blocks_candidates_and_reports_zero(self):
        result = self.worker.audit_shard(self.rows([self.candidate()]))
        self.assertEqual(result["admissible_candidate_counts_not_published"]["yo"], 0)
        self.assertIn("source_not_uniquely_approved", result["review_queue"][0]["reasons"])
        self.assertEqual(self.worker.report(result)["ledger_sources_total"], 0)

    def test_exact_unicode_variants_not_silently_merged(self):
        first = self.candidate(record_id="a", lemma="ọ̀rọ̀", variant="yo-Latn")
        second = self.candidate(record_id="b", lemma="ọ̀rọ̀", variant="yo-Latn")
        third = self.candidate(record_id="c", lemma="ọ̀rọ̀", variant="yo-Latn-region-X")
        result = self.worker.audit_shard(self.rows([first, second, third]))
        self.assertTrue(any("spelling_meaning_or_provenance_conflict" in r["reasons"] for r in result["review_queue"]))
        self.assertEqual(result["candidate_counts"]["yo"], 3)
        self.assertEqual(first["lemma"], "ọ̀rọ̀")
        self.assertEqual(second["lemma"], "ọ̀rọ̀")

    def test_conflicting_meanings_and_reused_ids_reviewed(self):
        result = self.worker.audit_shard(self.rows([self.candidate(), self.candidate(meaning="word")]))
        self.assertIn("record_id_conflict", result["review_queue"][-1]["reasons"])
        self.assertIn("spelling_meaning_or_provenance_conflict", result["review_queue"][-1]["reasons"])

    def test_rights_and_community_speaker_consent_are_mandatory(self):
        result = self.worker.audit_shard(self.rows([self.candidate(community="community group")]))
        self.assertIn("missing_speaker_consent_reference", result["review_queue"][0]["reasons"])

    def test_bad_inputs_never_become_approved(self):
        path = self.root / "broken.jsonl"
        path.write_bytes(b'{"language_id":"yo","language_id":"sw"}\n\xff\n')
        result = self.worker.audit_shard(path)
        self.assertEqual(result["processed"], 2)
        self.assertEqual(len(result["review_queue"]), 2)
        self.assertEqual(result["candidate_counts"]["yo"], 0)

    def test_checkpoint_is_bounded_and_resumable(self):
        path = self.rows([self.candidate(record_id=str(i)) for i in range(5)])
        first = self.worker.audit_shard(path, max_rows=2)
        second = self.worker.audit_shard(path, start_line=first["next_line"], max_rows=2)
        self.assertEqual((first["processed"], first["next_line"]), (2, 3))
        self.assertEqual((second["processed"], second["next_line"]), (2, 5))
        with self.assertRaises(audit.EvidenceError):
            self.worker.audit_shard(path, max_rows=2001)

    def test_forged_approval_without_retrieval_proof_rejected(self):
        self.write_json("legal/ledger/sources.json", {"schema_version": "1.0.0", "sources": [{"source_id": "fake_source",
            "status": "APPROVED_FOR_REDISTRIBUTION", "review": {"ok": True},
            "retrieval": {"not_sha": "fake"}, "license": "CC BY 4.0", "publisher": "publisher",
            "rights_url": "https://example.org/rights", "languages": ["yo"]}]})
        worker = audit.DiverseAudit(root=self.root)
        result = worker.audit_shard(self.rows([self.candidate()]))
        self.assertEqual(result["admissible_candidate_counts_not_published"]["yo"], 0)
        self.assertIn("redistribution_rights_unverified", result["review_queue"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
