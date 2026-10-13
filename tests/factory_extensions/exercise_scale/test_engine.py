"""Synthetic-only negative QA. These records are not licensed course content."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.factory_extensions.exercise_scale.engine import (
    ExerciseError, audit_partition, grade_response, validate_candidate,
)


def sample():
    text = "Das Buch ist neu."
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    c = {
        "schema_version": "1.0.0", "type": "cloze", "language": "de",
        "source_language": "de", "target_language": "de",
        "interface_language": "ar", "script": "Latn", "directed_pair_id": None,
        "source_sense_id": None, "sense_id": "sense.de.book",
        "lexeme_id": "lex.de.book", "grammar_rule_id": None,
        "proficiency": {"framework_id": "CEFR", "level_id": "A1",
                        "evidence_id": "prof.de.book"},
        "difficulty": "beginner", "prompt": "Das ____ ist neu.",
        "correct_answers": ["Buch"], "ambiguous_answers": [],
        "answer_policy": {"unicode": "NFC", "diacritics": "strict"},
        "choices": [], "matching_pairs": [],
        "features": {"number": "singular"},
        "cloze_source": text, "cloze_span": [4, 8],
        "evidence": {
            "source_id": "fixture.tatoeba", "publisher": "Example Publisher",
            "dataset_version": "fixture-v1", "locator": "sentence/1",
            "origin_url": "https://example.org/1", "license_id": "CC0-1.0",
            "artifact_sha256": "a" * 64, "record_sha256": digest,
            "answer_evidence_url": "https://example.org/answer/1",
        },
        "review": {"approved": True, "reviewer_id": "editor-1",
                   "decision_url": "https://example.org/review/1",
                   "answer_unambiguous": True, "distractors_reviewed": True},
        "explanation": None, "fixture_only": True,
        "publication_approved": False,
    }
    references = {
        "languages": {"de": {"scripts": ["Latn"]}, "ar": {"scripts": ["Arab"]},
                      "ja": {"scripts": ["Jpan"]}, "zh": {"scripts": ["Hans", "Hant"]}},
        "sources": {"fixture.tatoeba": {
            "status": "APPROVED_FOR_REDISTRIBUTION", "publisher": "Example Publisher",
            "dataset_version": "fixture-v1", "license_id": "CC0-1.0",
            "artifact_sha256": "a" * 64}},
        "senses": {"sense.de.book": {"language": "de", "lexeme_id": "lex.de.book",
                                   "approved": True}},
        "pairs": {}, "forms": {}, "rules": {}, "proficiency": {
            "prof.de.book": {"language": "de", "framework_id": "CEFR",
                             "level_id": "A1", "approved": True}},
        "distractors": {},
    }
    return c, references


class ExerciseScaleTests(unittest.TestCase):
    def assert_rejected(self, candidate, refs, code):
        with self.assertRaisesRegex(ExerciseError, code):
            validate_candidate(candidate, refs)

    def test_review_only_not_publication(self):
        c, r = sample()
        receipt = validate_candidate(c, r)
        self.assertEqual("REVIEW_REQUIRED", receipt["status"])
        self.assertFalse(receipt["publication_approved"])
        self.assertEqual(64, len(receipt["candidate_sha256"]))

    def test_all_eight_types_have_independent_evidence_gate(self):
        c, r = sample()
        for kind in ("recognition", "recall", "multiple_choice", "cloze",
                     "matching", "spelling", "verb_conjugation", "grammar"):
            x = copy.deepcopy(c)
            x["type"] = kind
            if kind != "cloze":
                x["cloze_source"], x["cloze_span"] = None, None
            if kind == "multiple_choice":
                x["choices"] = [
                    {"text": "Buch", "evidence_id": "correct"},
                    {"text": "Haus", "evidence_id": "d1"},
                    {"text": "Katze", "evidence_id": "d2"},
                ]
                r["distractors"] = {
                    "d1": {"language": "de", "text": "Haus", "approved": True,
                           "not_equivalent_review_url": "https://example.org/d1"},
                    "d2": {"language": "de", "text": "Katze", "approved": True,
                           "not_equivalent_review_url": "https://example.org/d2"},
                }
            if kind == "matching":
                x["matching_pairs"] = [
                    {"left": "A", "right": "B", "edge_id": "e1"},
                    {"left": "C", "right": "D", "edge_id": "e2"},
                ]
                r["pairs"] = {
                    "e1": {"source_language": "de", "target_language": "de",
                           "approved": True, "source_text": "A", "target_text": "B"},
                    "e2": {"source_language": "de", "target_language": "de",
                           "approved": True, "source_text": "C", "target_text": "D"},
                }
            if kind in ("grammar", "verb_conjugation"):
                x["grammar_rule_id"] = "rule.de.1"
                r["rules"]["rule.de.1"] = {"language": "de", "approved": True,
                    "explanation": "Reviewed rule explanation."}
                x["explanation"] = "Reviewed rule explanation."
            if kind == "verb_conjugation":
                r["forms"]["f1"] = {"language": "de", "sense_id": "sense.de.book",
                    "text": "Buch", "features": {"number": "singular"}, "approved": True}
                x["form_evidence_id"] = "f1"
            if kind not in ("cloze", "matching"):
                x["prompt"] = "Complete the reviewed task."
            self.assertEqual("REVIEW_REQUIRED", validate_candidate(x, r)["status"], kind)

    def test_missing_approved_source_or_fixture_rights(self):
        c, r = sample()
        r["sources"] = {}
        self.assert_rejected(c, r, "SOURCE_NOT_APPROVED")

    def test_reversed_pair(self):
        c, r = sample()
        c.update(source_language="ar", source_sense_id="sense.ar.book",
                 directed_pair_id="ar-de")
        r["senses"]["sense.ar.book"] = {"language": "ar", "lexeme_id": "lex.ar.book", "approved": True}
        r["pairs"]["ar-de"] = {"source_language": "de", "target_language": "ar",
                                 "source_sense_id": "sense.de.book",
                                 "target_sense_id": "sense.ar.book", "approved": True}
        self.assert_rejected(c, r, "DIRECTION_EVIDENCE_MISMATCH")

    def test_unregistered_or_wrong_script(self):
        c, r = sample()
        c["language"] = "invented"
        self.assert_rejected(c, r, "UNREGISTERED_LANGUAGE")
        c, r = sample()
        c["script"] = "Arab"
        self.assert_rejected(c, r, "SCRIPT_MISMATCH")

    def test_stale_source_and_forged_review(self):
        c, r = sample()
        c["cloze_source"] = "Das Haus ist neu."
        self.assert_rejected(c, r, "SOURCE_TEXT_HASH_MISMATCH")
        c, r = sample()
        c["review"]["approved"] = False
        self.assert_rejected(c, r, "EDITORIAL_REVIEW_REQUIRED")

    def test_grammar_without_reviewed_rule(self):
        c, r = sample()
        c["type"], c["cloze_source"], c["cloze_span"] = "grammar", None, None
        c["prompt"], c["grammar_rule_id"] = "Choose form.", "rule.de.1"
        c["explanation"] = "Invented!"
        self.assert_rejected(c, r, "GRAMMAR_EVIDENCE_REQUIRED")

    def test_diacritics_are_never_globally_removed(self):
        self.assertEqual("CORRECT", grade_response("e\u0301", ["é"], [], "strict"))
        self.assertEqual("UNVERIFIED", grade_response("قلب", ["قَلْب"], [], "strict"))
        self.assertEqual("CORRECT", grade_response("قلب", ["قَلْب", "قلب"], [], "explicit_variants"))
        self.assertEqual("AMBIGUOUS", grade_response("dar", ["der"], ["dar"], "strict"))

    def test_choice_equivalence_requires_independent_review(self):
        c, r = sample()
        c["type"], c["cloze_source"], c["cloze_span"] = "multiple_choice", None, None
        c["prompt"] = "Pick a reviewed choice."
        c["choices"] = [{"text": "Buch", "evidence_id": "correct"},
                        {"text": "Bücher", "evidence_id": "d1"},
                        {"text": "Haus", "evidence_id": "d2"}]
        self.assert_rejected(c, r, "DISTRACTOR_NOT_ATTESTED")

    def test_leaked_answer_and_trivial_prompt(self):
        c, r = sample()
        c["prompt"] = "Buch"
        self.assert_rejected(c, r, "ANSWER_LEAK_OR_TRIVIAL")

    def test_unknown_proficiency_not_guessed(self):
        c, r = sample()
        c["proficiency"]["level_id"] = "C2"
        self.assert_rejected(c, r, "PROFICIENCY_EVIDENCE_MISMATCH")

    def test_batch_digest_and_duplicates(self):
        c, r = sample()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "shard.jsonl"
            data = (json.dumps(c, ensure_ascii=False) + "\n").encode("utf-8")
            p.write_bytes(data)
            report = audit_partition(p, hashlib.sha256(data).hexdigest(), r)
            self.assertEqual(1, report["candidates_review_required"])
            self.assertEqual(0, report["verified_exercises"])
            self.assertEqual(1, report["count_by_language"]["de"]["cloze"]["beginner"])
            with self.assertRaisesRegex(ExerciseError, "INPUT_SHA256_MISMATCH"):
                audit_partition(p, "0" * 64, r)
            p.write_bytes(data + data)
            with self.assertRaisesRegex(ExerciseError, "DUPLICATE_EXERCISE"):
                audit_partition(p, hashlib.sha256(p.read_bytes()).hexdigest(), r)


if __name__ == "__main__":
    unittest.main()
