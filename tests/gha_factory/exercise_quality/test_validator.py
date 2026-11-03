"""Synthetic-only Cloze replay QA tests. No production educational claims."""
import hashlib
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.gha_factory.examples.factory import make_cloze
from tools.gha_factory.exercise_quality.validator import (ExerciseError, evaluate_response, verify_cloze)


class ExerciseQualityTests(unittest.TestCase):
    def setUp(self):
        text = 'Das Buch ist neu.'
        self.sentence = {'id': 'source-101', 'language': 'de', 'text': text,
                         'admitted': True, 'license': 'CC0-1.0',
                         'attribution': 'https://tatoeba.org/en/sentences/show/101',
                         'source_sha256': 'a'*64}
        self.senses = {x: {'language': 'de', 'lexeme_id': 'de:' + x, 'approved': True}
                       for x in ('book','house','cat')}
        self.annotation = {'sentence_id': 'source-101', 'language': 'de',
                           'sentence_sha256': hashlib.sha256(text.encode()).hexdigest(),
                           'source_sha256': 'a'*64,
                           'editorial_unambiguous': True, 'editor_review_url': 'https://example.org/review/101',
                           'start': 4, 'end': 8, 'sense_id': 'book', 'lexeme_id': 'de:book',
                           'features': {'number':'singular','case':'nominative'},
                           'distractors': [{'surface':'Haus','sense_id':'house'},
                                           {'surface':'Katze','sense_id':'cat'}]}
        self.forms = {('de', sid, surface, (('case','nominative'),('number','singular')))
                      for sid, surface in [('book','Buch'),('house','Haus'),('cat','Katze')]}
        self.exercise = make_cloze(self.sentence, self.annotation, self.senses, self.forms)

    def valid(self):
        return verify_cloze(self.exercise, self.sentence, self.annotation,
                            self.senses, self.forms, {'de','ar','en','es','fr'})

    def test_verified_candidate_remains_review_required(self):
        receipt = self.valid()
        self.assertEqual('REVIEW_REQUIRED', receipt['quality_status'])
        self.assertFalse(receipt['publication_approved'])
        self.assertEqual(64, len(receipt['candidate_sha256']))

    def test_wrong_language_identity(self):
        with self.assertRaisesRegex(ExerciseError, 'UNREGISTERED_LANGUAGE'):
            verify_cloze(self.exercise, self.sentence, self.annotation, self.senses, self.forms, {'ar'})

    def test_stale_answer_rejected(self):
        self.exercise['answer'] = 'Haus'
        with self.assertRaisesRegex(ExerciseError, 'CANDIDATE_TAMPERED'):
            self.valid()

    def test_unreviewed_editorial_annotation_rejected(self):
        self.annotation['editorial_unambiguous'] = False
        with self.assertRaisesRegex(ExerciseError, 'GHA05_EVIDENCE_GATE_REJECTED'):
            self.valid()

    def test_unlicensed_or_unadmitted_source_rejected(self):
        self.sentence['license'] = 'CC-BY-2.0-FR'
        with self.assertRaisesRegex(ExerciseError, 'LICENSE_REVIEW_REQUIRED'):
            self.valid()
        self.sentence['license'] = 'CC0-1.0'
        self.sentence['admitted'] = False
        with self.assertRaisesRegex(ExerciseError, 'UNADMITTED_SENTENCE'):
            self.valid()

    def test_wrong_source_sha_rejected(self):
        self.annotation['source_sha256'] = 'b'*64
        with self.assertRaisesRegex(ExerciseError, 'ANNOTATION_SOURCE_MISMATCH'):
            self.valid()

    def test_unsupported_distractor_rejected(self):
        self.forms.remove(('de','cat','Katze',(('case','nominative'),('number','singular'))))
        with self.assertRaisesRegex(ExerciseError, 'GHA05_EVIDENCE_GATE_REJECTED'):
            self.valid()

    def test_unhashable_language_evidence_is_rejected_cleanly(self):
        self.sentence['language'] = ['de']
        with self.assertRaisesRegex(ExerciseError, 'UNREGISTERED_LANGUAGE'):
            self.valid()

    def test_unpaired_surrogate_in_sentence_is_rejected_before_replay(self):
        self.sentence['text'] = 'B\ud800uch ist neu.'
        with self.assertRaisesRegex(ExerciseError, 'INVALID_ORIGINAL_TEXT'):
            self.valid()

    def test_response_exact_and_unicode_normalization(self):
        self.assertEqual('CORRECT',evaluate_response('Buch',{'Buch'}))
        self.assertEqual('CORRECT',evaluate_response('e\u0301',{'é'}))

    def test_response_only_attested_ambiguous(self):
        self.assertEqual('AMBIGUOUS',evaluate_response('variant',{'standard'},{'variant'}))
        self.assertEqual('UNVERIFIED',evaluate_response('standrd',{'standard'}))

    def test_cloze_cannot_split_unicode_grapheme(self):
        # Combining diaeresis belongs to its preceding Latin base character.
        text = 'B\u0308uch ist neu.'
        self.sentence['text'] = text
        self.annotation['sentence_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        self.annotation['start'], self.annotation['end'] = 0, 1
        self.forms.add(('de','book','B',(('case','nominative'),('number','singular'))))
        self.exercise = make_cloze(self.sentence, self.annotation, self.senses, self.forms)
        with self.assertRaisesRegex(ExerciseError, 'SPLIT_UNICODE_GRAPHEME'):
            self.valid()

    def test_rejects_indic_conjunct_inside_grapheme(self):
        from tools.gha_factory.exercise_quality.validator import _grapheme_cut
        for word, cut in [('क्ष', 2), ('क्‍ष', 2), ('क्‍ष', 3)]:
            with self.subTest(word=word, cut=cut):
                self.assertTrue(_grapheme_cut(word, cut))
        self.assertFalse(_grapheme_cut('क्‍ष', 4))

    def test_rejects_boundaries_inside_emoji_flags_and_hangul(self):
        from tools.gha_factory.exercise_quality.validator import _grapheme_cut
        self.assertTrue(_grapheme_cut('🇩🇪', 1))
        self.assertTrue(_grapheme_cut('👩‍💻', 1))
        self.assertTrue(_grapheme_cut('한', 1))

    def test_nfc_duplicate_options_rejected_after_canonical_replay(self):
        exercise = dict(self.exercise)
        exercise['options'] = ['Buch', 'é', 'e\u0301']
        with patch('tools.gha_factory.exercise_quality.validator.make_cloze',
                   return_value=exercise):
            with self.assertRaisesRegex(ExerciseError, 'DUPLICATE_CHOICES'):
                verify_cloze(exercise, self.sentence, self.annotation,
                             self.senses, self.forms, {'de'})

    def test_locale_specific_choice_replay(self):
        # Synthetic replay fixture: no claim of source or publication approval.
        for language, options in (('tr', ['I', 'i', 'kitap']),
                                  ('de', ['Maße', 'Masse', 'Buch'])):
            with self.subTest(language=language):
                sentence = dict(self.sentence, language=language)
                exercise = dict(self.exercise, language=language, options=options)
                with patch('tools.gha_factory.exercise_quality.validator.make_cloze',
                           return_value=exercise):
                    receipt = verify_cloze(exercise, sentence, self.annotation,
                                           self.senses, self.forms, {'tr', 'de'})
                self.assertEqual('REVIEW_REQUIRED', receipt['quality_status'])
        for options in (['I', 'ı', 'kitap'], ['İ', 'i', 'kitap']):
            sentence = dict(self.sentence, language='tr')
            exercise = dict(self.exercise, language='tr', options=options)
            with self.subTest(options=options), patch(
                    'tools.gha_factory.exercise_quality.validator.make_cloze',
                    return_value=exercise):
                with self.assertRaisesRegex(ExerciseError, 'DUPLICATE_CHOICES'):
                    verify_cloze(exercise, sentence, self.annotation,
                                 self.senses, self.forms, {'tr'})

    def test_nfc_equivalent_attested_alternate_is_ambiguous(self):
        self.assertEqual('AMBIGUOUS', evaluate_response('e\u0301', {'other'}, {'é'}))

    def test_nfc_equivalent_evidence_conflict_rejected(self):
        with self.assertRaisesRegex(ExerciseError, 'CONFLICTING_ANSWER_EVIDENCE'):
            evaluate_response('x', {'é'}, {'e\u0301'})

    def test_conflicting_alternate_prohibited(self):
        with self.assertRaisesRegex(ExerciseError, 'CONFLICTING_ANSWER_EVIDENCE'):
            evaluate_response('x',{'x'},{'x'})


    def test_oversized_sentence_rejected_before_replay(self):
        # Synthetic attested-looking fixture: source importer permits <=2000 chars.
        self.sentence['text'] = 'B' * 2001
        with patch('tools.gha_factory.exercise_quality.validator.make_cloze',
                   return_value=self.exercise):
            with self.assertRaisesRegex(ExerciseError, 'OVERSIZED_SENTENCE'):
                self.valid()

    def test_blank_attestation_evidence_never_grades_correct_or_ambiguous(self):
        # Whitespace is not a source-backed lexical answer.
        with self.assertRaisesRegex(ExerciseError, 'INVALID_ANSWER_EVIDENCE'):
            evaluate_response(' ', {' '})
        with self.assertRaisesRegex(ExerciseError, 'INVALID_ALTERNATE_EVIDENCE'):
            evaluate_response(' ', {'Buch'}, {'\t'})


if __name__ == '__main__':
    unittest.main()
