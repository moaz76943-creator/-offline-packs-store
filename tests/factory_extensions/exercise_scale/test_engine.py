"""Synthetic-only negative QA. These records are not licensed course content."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.factory_extensions.exercise_scale.engine import (
    ExerciseError, audit_partition, grade_response, reviewed_sha256, validate_candidate,
)


def refresh(candidate, refs, reviewer="editor-1"):
    """Rebind the independent receipt after a test mutates reviewed fields."""
    digest = reviewed_sha256(candidate)
    reviews = refs["editor_reviews"]
    claim = candidate["review"]["decision_url"]
    if isinstance(reviews.get(reviewer), list):
        for item in reviews[reviewer]:
            if item.get("decision_url") == claim:
                item["answers_sha256"] = digest
                item["sense_id"] = candidate["sense_id"]
                item["source_id"] = candidate["evidence"]["source_id"]
                item["record_sha256"] = candidate["evidence"]["record_sha256"]
        return
    receipt = reviews[reviewer]
    receipt["answers_sha256"] = digest
    receipt["sense_id"] = candidate["sense_id"]
    receipt["source_id"] = candidate["evidence"]["source_id"]
    receipt["record_sha256"] = candidate["evidence"]["record_sha256"]


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
                                   "approved": True, "attested_answers": ["Buch"]}},
        "pairs": {}, "forms": {}, "rules": {}, "proficiency": {
            "prof.de.book": {"language": "de", "framework_id": "CEFR",
                             "level_id": "A1", "sense_id": "sense.de.book", "approved": True}},
        "distractors": {},
        "editor_reviews": {"editor-1": {"approved": True,
            "decision_url": "https://example.org/review/1",
            "source_id": "fixture.tatoeba", "record_sha256": digest,
            "sense_id": "sense.de.book",
            "answers_sha256": reviewed_sha256(c)}},
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
            refresh(x, r)
            self.assertEqual("REVIEW_REQUIRED", validate_candidate(x, r)["status"], kind)

    def test_invented_editorial_approval_is_rejected(self):
        c, r = sample()
        r["editor_reviews"] = {}
        self.assert_rejected(c, r, "INDEPENDENT_EDITORIAL_EVIDENCE_REQUIRED")

    def test_stale_answer_review_is_rejected(self):
        c, r = sample()
        r["editor_reviews"]["editor-1"]["answers_sha256"] = "b" * 64
        self.assert_rejected(c, r, "INDEPENDENT_EDITORIAL_EVIDENCE_REQUIRED")

    def test_candidate_must_never_claim_publication(self):
        c, r = sample()
        c["publication_approved"] = True
        self.assert_rejected(c, r, "CANDIDATE_PUBLICATION_FORBIDDEN")

    def test_editorial_decision_url_cannot_be_substituted(self):
        c, r = sample()
        c["review"]["decision_url"] = "https://example.org/review/fake"
        self.assert_rejected(c, r, "INDEPENDENT_EDITORIAL_EVIDENCE_REQUIRED")

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
        refresh(c, r)
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
        refresh(c, r)
        self.assert_rejected(c, r, "DISTRACTOR_NOT_ATTESTED")

    def test_leaked_answer_and_trivial_prompt(self):
        c, r = sample()
        c["prompt"] = "Buch"
        refresh(c, r)
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

    def _recall(self, prompt, answers):
        c, r = sample()
        c["type"] = "recall"
        c["cloze_source"], c["cloze_span"] = None, None
        c["prompt"] = prompt
        c["correct_answers"] = answers
        r["senses"]["sense.de.book"]["attested_answers"] = list(answers)
        refresh(c, r)
        return c, r

    def test_answers_must_match_independent_sense_evidence(self):
        c, r = self._recall("Name the reviewed sense.", ["definitely unrelated"])
        r["senses"]["sense.de.book"]["attested_answers"] = ["Buch"]
        self.assert_rejected(c, r, "ANSWER_SENSE_EVIDENCE_MISMATCH")
        for kind in ("recognition", "recall", "multiple_choice", "spelling", "grammar"):
            with self.subTest(kind=kind):
                c, r = self._recall("Name the reviewed sense.", ["definitely unrelated"])
                c["type"] = kind
                if kind == "multiple_choice":
                    c["choices"] = [
                        {"text": "definitely unrelated", "evidence_id": "correct"},
                        {"text": "Haus", "evidence_id": "d1"},
                        {"text": "Katze", "evidence_id": "d2"},
                    ]
                    r["distractors"] = {
                        "d1": {"language": "de", "text": "Haus", "approved": True,
                               "not_equivalent_review_url": "https://example.org/d1"},
                        "d2": {"language": "de", "text": "Katze", "approved": True,
                               "not_equivalent_review_url": "https://example.org/d2"},
                    }
                if kind == "grammar":
                    c["grammar_rule_id"] = "rule.de.1"
                    c["explanation"] = "Reviewed rule explanation."
                    r["rules"]["rule.de.1"] = {"language": "de", "approved": True,
                                               "explanation": "Reviewed rule explanation."}
                r["senses"]["sense.de.book"]["attested_answers"] = ["Buch"]
                refresh(c, r)
                self.assert_rejected(c, r, "ANSWER_SENSE_EVIDENCE_MISMATCH")
        c, r = self._recall("Name the reviewed sense.", ["Buch"])
        r["senses"]["sense.de.book"].pop("attested_answers")
        self.assert_rejected(c, r, "ANSWER_SENSE_EVIDENCE_MISMATCH")
        digest = reviewed_sha256(c)
        r["editor_reviews"]["editor-1"]["answers_sha256"] = digest
        from tools.factory_extensions.exercise_scale.engine import _answer_digest
        r["senses"]["sense.de.book"]["answer_sha256"] = _answer_digest(["nope"])
        self.assert_rejected(c, r, "ANSWER_SENSE_EVIDENCE_MISMATCH")
        r["senses"]["sense.de.book"]["answer_sha256"] = _answer_digest(["Buch"])
        self.assertEqual("REVIEW_REQUIRED", validate_candidate(c, r)["status"])

    def test_short_answer_inside_unrelated_word_is_not_a_leak(self):
        c, r = self._recall("Translate this word.", ["a"])
        self.assertEqual("REVIEW_REQUIRED", validate_candidate(c, r)["status"])
        c, r = self._recall("Translate a word.", ["a"])
        self.assert_rejected(c, r, "ANSWER_LEAK_OR_TRIVIAL")

    def test_nfc_equivalent_exercises_share_a_fingerprint(self):
        c, r = self._recall("Say café", ["Buch"])
        other = copy.deepcopy(c)
        other["prompt"] = "Say cafe\u0301"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shard.jsonl"
            payload = (json.dumps(c, ensure_ascii=False) + "\n" + json.dumps(other, ensure_ascii=False) + "\n").encode("utf-8")
            path.write_bytes(payload)
            with self.assertRaisesRegex(ExerciseError, "DUPLICATE_EXERCISE"):
                audit_partition(path, hashlib.sha256(payload).hexdigest(), r)

    def test_nfc_choice_position_is_counted(self):
        records = []
        _, refs = sample()
        refs["distractors"] = {
            "d1": {"language": "de", "text": "Haus", "approved": True,
                   "not_equivalent_review_url": "https://example.org/d1"},
            "d2": {"language": "de", "text": "Katze", "approved": True,
                   "not_equivalent_review_url": "https://example.org/d2"},
        }
        refs["senses"]["sense.de.book"]["attested_answers"] = ["é"]
        refs["editor_reviews"] = {"editor-1": []}
        for index in range(4):
            c, _ = sample()
            c["type"] = "multiple_choice"
            c["cloze_source"], c["cloze_span"] = None, None
            c["prompt"] = f"Pick the reviewed form {index}."
            c["correct_answers"] = ["é"]
            c["choices"] = [
                {"text": "e\u0301", "evidence_id": "correct"},
                {"text": "Haus", "evidence_id": "d1"},
                {"text": "Katze", "evidence_id": "d2"},
            ]
            c["review"]["decision_url"] = f"https://example.org/review/mc/{index}"
            refs["editor_reviews"]["editor-1"].append({
                "approved": True, "decision_url": c["review"]["decision_url"],
                "source_id": c["evidence"]["source_id"], "record_sha256": c["evidence"]["record_sha256"],
                "sense_id": c["sense_id"], "answers_sha256": reviewed_sha256(c),
            })
            records.append(c)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mc.jsonl"
            payload = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in records).encode("utf-8")
            path.write_bytes(payload)
            with self.assertRaisesRegex(ExerciseError, "REPEATED_ANSWER_POSITION"):
                audit_partition(path, hashlib.sha256(payload).hexdigest(), refs)

    def test_oversized_jsonl_line_is_bounded(self):
        c, r = sample()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "huge.jsonl"
            path.write_bytes(b"{" + (b" " * 1048576) + b"}\n")
            with self.assertRaisesRegex(ExerciseError, "PARTITION_BOUNDS_EXCEEDED"):
                audit_partition(path, hashlib.sha256(path.read_bytes()).hexdigest(), r)

    def test_checkpoint_includes_references_digest(self):
        c, r = sample()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shard.jsonl"
            data = (json.dumps(c, ensure_ascii=False) + "\n").encode("utf-8")
            path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            first = audit_partition(path, digest, r, references_sha256="a" * 64)
            second = audit_partition(path, digest, r, references_sha256="b" * 64)
            self.assertEqual(first["references_sha256"], "a" * 64)
            self.assertNotEqual(first["checkpoint_sha256"], second["checkpoint_sha256"])
            with self.assertRaisesRegex(ExerciseError, "REFERENCES_SHA256_MISMATCH"):
                audit_partition(path, digest, r, references_sha256="not-a-digest")

    def test_receipt_covers_prompt_and_ambiguous_answers(self):
        c, r = sample()
        c["prompt"] = "Das ____ bleibt neu."
        self.assert_rejected(c, r, "INDEPENDENT_EDITORIAL_EVIDENCE_REQUIRED")
        c, r = sample()
        c["ambiguous_answers"] = ["Band"]
        self.assert_rejected(c, r, "INDEPENDENT_EDITORIAL_EVIDENCE_REQUIRED")
        refresh(c, r)
        self.assertEqual("REVIEW_REQUIRED", validate_candidate(c, r)["status"])

    def test_one_reviewer_can_approve_multiple_exercises(self):
        first, refs = self._recall("Name the reviewed sense.", ["Buch"])
        second, _ = self._recall("Name another reviewed sense.", ["Buch"])
        second["review"]["decision_url"] = "https://example.org/review/2"
        refs["editor_reviews"] = {"editor-1": [
            {"approved": True, "decision_url": first["review"]["decision_url"],
             "source_id": first["evidence"]["source_id"], "record_sha256": first["evidence"]["record_sha256"],
             "sense_id": first["sense_id"], "answers_sha256": reviewed_sha256(first)},
            {"approved": True, "decision_url": second["review"]["decision_url"],
             "source_id": second["evidence"]["source_id"], "record_sha256": second["evidence"]["record_sha256"],
             "sense_id": second["sense_id"], "answers_sha256": reviewed_sha256(second)},
        ]}
        self.assertEqual("REVIEW_REQUIRED", validate_candidate(first, refs)["status"])
        self.assertEqual("REVIEW_REQUIRED", validate_candidate(second, refs)["status"])

    def test_proficiency_must_name_the_exercise_subject(self):
        c, r = sample()
        r["proficiency"]["prof.de.book"].pop("sense_id")
        self.assert_rejected(c, r, "PROFICIENCY_EVIDENCE_MISMATCH")
        c, r = sample()
        r["proficiency"]["prof.de.book"]["sense_id"] = "sense.de.other"
        self.assert_rejected(c, r, "PROFICIENCY_EVIDENCE_MISMATCH")
        c, r = sample()
        r["proficiency"]["prof.de.book"]["subject_id"] = c["lexeme_id"]
        r["proficiency"]["prof.de.book"].pop("sense_id")
        self.assertEqual("REVIEW_REQUIRED", validate_candidate(c, r)["status"])


if __name__ == "__main__":
    unittest.main()
