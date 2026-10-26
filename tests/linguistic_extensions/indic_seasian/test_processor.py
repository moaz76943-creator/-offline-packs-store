"""Synthetic orthographic fixtures only: no fabricated lexeme release claims."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import unicodedata

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.linguistic_extensions.indic_seasian import processor as p


SAMPLES = {
    'hi': 'हिन्दी', 'mr': 'मराठी', 'ne': 'नेपाली',
    'bn': 'বাংলা', 'as': 'অসমীয়া', 'pa': 'ਪੰਜਾਬੀ',
    'gu': 'ગુજરાતી', 'or': 'ଓଡ଼ିଆ', 'ta': 'தமிழ்',
    'te': 'తెలుగు', 'kn': 'ಕನ್ನಡ', 'ml': 'മലയാളം',
    'si': 'සිංහල', 'ur': 'اردو', 'th': 'ภาษาไทย',
    'lo': 'ພາສາລາວ', 'km': 'ភាសាខ្មែរ', 'my': 'မြန်မာ',
}


class ScriptAwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = {'languages': [
            {'id': code, 'scripts': list(scripts), 'family': 'synthetic-test-metadata'}
            for code, scripts in p.LANGUAGE_SCRIPTS.items()]}
        cls.ledger = {'sources': []}

    def test_canonical_public_registry_is_independently_consistent(self):
        path = ROOT / 'catalog/language_registry.v1.json'
        if not path.exists():
            self.skipTest('public canonical catalog absent from isolated unit checkout')
        registry = json.loads(path.read_text(encoding='utf-8'))
        for code in SAMPLES:
            with self.subTest(code=code):
                record = p.profile(code, registry)
                self.assertEqual(code, record['language'])
                self.assertEqual('evidence_required_no_generated_forms', record['morphology'])
        self.assertEqual('Indo-Aryan', p.profile('ur', registry)['family'])
        self.assertEqual(['Guru', 'Arab'], p.profile('pa', registry)['scripts'])

    def test_positive_script_search_roundtrip_for_each_of_18_languages(self):
        self.assertEqual(18, len(SAMPLES))
        for code, sample in SAMPLES.items():
            with self.subTest(code=code):
                checked = p.validate_text(code, sample)
                self.assertEqual(sample.encode('utf-8'), checked['original'].encode('utf-8'))
                self.assertEqual(hashlib.sha256(sample.encode('utf-8')).hexdigest(),
                                 checked['original_utf8_sha256'])
                self.assertEqual(unicodedata.normalize('NFC', sample), checked['search_key'])
                self.assertEqual('unicode_canonical_equivalent',
                                 p.search_relation(code, sample, unicodedata.normalize('NFD', sample)))
                self.assertEqual(sample, ''.join(p.orthographic_units(code, sample)))

    def test_negative_mixed_script_search_and_control_for_each_language(self):
        for code, sample in SAMPLES.items():
            with self.subTest(code=code):
                for invalid in (sample + 'A', sample + '\u202e', sample + '\x00',
                                'A' + sample, '\ud800' + sample):
                    with self.assertRaises(p.ScriptContractError):
                        p.validate_text(code, invalid)
                with self.assertRaises(p.ScriptContractError):
                    p.search_relation(code, sample, 'A' + sample)

    def test_akshara_boundaries_and_combining_vowel_signs(self):
        self.assertEqual(('क्षि',), p.orthographic_units('hi', 'क्षि'))
        self.assertEqual(('ক্ষি',), p.orthographic_units('bn', 'ক্ষি'))
        self.assertEqual(('കി',), p.orthographic_units('ml', 'കി'))
        self.assertEqual(('कि',), p.orthographic_units('hi', 'कि'))
        self.assertEqual(('क्\u200dष',), p.orthographic_units('hi', 'क्\u200dष'))
        self.assertEqual(('क्\u200c', 'ष'), p.orthographic_units('hi', 'क्\u200cष'))
        self.assertEqual('undetermined_not_transliteration_or_lexical_equivalence',
                         p.search_relation('hi', 'हिन्दी', 'हिंदी'))

    def test_distinct_identity_even_for_shared_writing_system(self):
        with self.assertRaises(p.ScriptContractError):
            p.validate_text('bn', 'हिन्दी')
        self.assertNotEqual(p.profile('bn', self.registry)['language'],
                            p.profile('as', self.registry)['language'])
        self.assertNotEqual(p.profile('hi', self.registry)['language'],
                            p.profile('mr', self.registry)['language'])
        self.assertEqual('Arab', p.validate_text('pa', 'پنجابی')['script'])
        with self.assertRaises(p.ScriptContractError):
            p.validate_text('pa', 'ਪنجابی')
        with self.assertRaises(p.ScriptContractError):
            p.profile('ar', self.registry)

    def test_southeast_asian_segmentation_never_guesses_words(self):
        for code in ('th', 'lo', 'km', 'my'):
            with self.subTest(code=code):
                result = p.words(code, SAMPLES[code])
                self.assertEqual([], result['tokens'])
                self.assertEqual('requires_attested_segmentation', result['status'])
                with self.assertRaises(p.ScriptContractError):
                    p.words(code, SAMPLES[code], attested=self._segment(code), ledger=self.ledger)
                self.assertEqual([SAMPLES[code]],
                                 p.words(code, SAMPLES[code], attested=self._segment(code),
                                         ledger=self._approved(code))['tokens'])
        self.assertEqual('orthographic_hints_only', p.words('hi', 'हिन्दी भाषा')['status'])
        self.assertEqual(['हिन्दी', 'भाषा'], p.words('hi', 'हिन्दी भाषा')['tokens'])
        with self.assertRaises(p.ScriptContractError):
            p.words('th', SAMPLES['th'],
                    attested={**self._segment('th'), 'tokens': ['ภ', 'า']},
                    ledger=self._approved('th'))

    def test_unapproved_forms_fail_closed_and_urdu_is_not_arabic_grammar(self):
        example = self._record('ur', 'اردو', {'case': 'oblique'})
        with self.assertRaises(p.ScriptContractError):
            p.validate_attestation(example, 'ur', self.registry, self.ledger)
        ledger = self._approved('ur')
        self.assertEqual('attested_only',
                         p.validate_attestation(example, 'ur', self.registry, ledger)['status'])
        for features in ({'root_pattern': 'fa3ala'}, {'noun_classes': 'a'},
                         {'case': ''}):
            with self.subTest(features=features), self.assertRaises(p.ScriptContractError):
                p.validate_attestation(self._record('ur', 'اردو', features),
                                       'ur', self.registry, ledger)
        with self.assertRaises(p.ScriptContractError):
            p.validate_attestation(example, 'hi', self.registry, ledger)

    def test_per_language_feature_gate(self):
        self.assertIn('postposition', p.profile('hi', self.registry)['candidate_feature_keys'])
        self.assertNotIn('postposition', p.profile('th', self.registry)['candidate_feature_keys'])
        self.assertIn('classifiers', p.profile('th', self.registry)['candidate_feature_keys'])
        self.assertNotIn('classifiers', p.profile('mr', self.registry)['candidate_feature_keys'])
        with self.assertRaises(p.ScriptContractError):
            p.validate_attestation(self._record('th', SAMPLES['th'], {'case': 'nominative'}),
                                   'th', self.registry, self._approved('th'))

    def test_bounded_worker_and_actual_nonfabricated_coverage(self):
        record = self._record('hi', SAMPLES['hi'], {'number': 'singular'})
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'forms.jsonl'
            line = json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n'
            file.write_text(line, encoding='utf-8')
            result = p.audit_jsonl(file, 'hi', self.registry, self._approved('hi'))
            self.assertEqual(1, result['verified_forms'])
            self.assertEqual(1, result['verified_lexemes'])
            self.assertEqual(hashlib.sha256(line.encode('utf-8')).hexdigest(),
                             result['input_sha256'])
            file.write_text(line * 2, encoding='utf-8')
            with self.assertRaises(p.ScriptContractError):
                p.audit_jsonl(file, 'hi', self.registry, self._approved('hi'))
            with self.assertRaises(p.ScriptContractError):
                p.audit_jsonl(file, 'hi', self.registry, self._approved('hi'), max_bytes=10)
            file.write_text('{"a":1,"a":2}\n', encoding='utf-8')
            with self.assertRaises(p.ScriptContractError):
                p.audit_jsonl(file, 'hi', self.registry, self._approved('hi'))

    def test_forged_attestation_with_same_source_and_unchanged_tags_rejected(self):
        valid = self._record('hi', SAMPLES['hi'], {'number': 'singular'})
        ledger = self._approved('hi')
        self.assertEqual('attested_only', p.validate_attestation(
            valid, 'hi', self.registry, ledger)['status'])
        forged = {**valid, 'form': 'हिंदी'}
        with self.assertRaises(p.ScriptContractError):
            p.validate_attestation(forged, 'hi', self.registry, ledger)
        with self.assertRaises(p.ScriptContractError):
            p.validate_attestation(valid, 'hi', self.registry, {'sources': [{
                **ledger['sources'][0], 'rights_status': 'UNVERIFIED_RIGHTS',
            }]})
        with self.assertRaises(p.ScriptContractError):
            p.validate_attestation(valid, 'hi', self.registry, {'sources': [{
                **ledger['sources'][0], 'rights_evidence_sha256': 'BAD',
            }]})

    def test_attested_tokenization_requires_reviewed_exact_boundary_digest(self):
        text = SAMPLES['th']
        one = self._segment('th')
        ledger = self._approved('th')
        self.assertEqual([text], p.words('th', text, attested=one, ledger=ledger)['tokens'])
        # Both alternatives reconstruct the exact UTF-8, but only ONE was reviewed.
        tampered = {**one, 'tokens': [text[:2], text[2:]]}
        self.assertEqual(text, ''.join(tampered['tokens']))
        with self.assertRaises(p.ScriptContractError):
            p.words('th', text, attested=tampered, ledger=ledger)

    def test_joiner_positions_are_checked_per_adjacent_character(self):
        self.assertEqual('Deva', p.validate_text('hi', 'क्\u200dष')['script'])
        self.assertEqual('Arab', p.validate_text('ur', 'ا\u200cب')['script'])
        for bad in ('\u200dक्ष', 'क्ष\u200d', 'क\u200dष', 'क्\u200d\u200dष',
                    'क्ष\u200cदेव'):
            with self.subTest(value=bad), self.assertRaises(p.ScriptContractError):
                p.validate_text('hi', bad)
        for bad in ('\u200cاردو', 'اردو\u200c', 'ا\u200c\u200cب'):
            with self.subTest(value=bad), self.assertRaises(p.ScriptContractError):
                p.validate_text('ur', bad)

    def test_empty_audit_is_not_a_production_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'empty.jsonl'
            file.write_bytes(b'')
            with self.assertRaises(p.ScriptContractError):
                p.audit_jsonl(file, 'hi', self.registry, self._approved('hi'))

    def test_ambiguous_duplicate_source_ids_fail_closed(self):
        approved = self._approved('hi')['sources'][0]
        same_id_unapproved = {'id': approved['id'], 'release_approved': False}
        with self.assertRaises(p.ScriptContractError):
            p.approved_sources({'sources': [same_id_unapproved, approved]})
        with self.assertRaises(p.ScriptContractError):
            p.approved_sources({'sources': [approved, same_id_unapproved]})

    def test_unbounded_worker_options_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'test.jsonl'
            file.write_bytes(b'')
            for budget in ({'max_records': 1000000}, {'max_bytes': 500000000},
                           {'max_records': True}, {'max_bytes': -1}):
                with self.subTest(budget=budget), self.assertRaises(p.ScriptContractError):
                    p.audit_jsonl(file, 'hi', self.registry, self._approved('hi'), **budget)

    def test_coverage_zero_when_no_approved_corpus(self):
        for code in SAMPLES:
            self.assertEqual(0, p.profile(code, self.registry)['lexeme_count'])
        self.assertEqual({}, p.approved_sources(self.ledger))
        with self.assertRaises(p.ScriptContractError):
            p.profile('hi', {'languages': [{'id': 'hi', 'scripts': ['Arab']}]})

    @staticmethod
    def _segment(code):
        text = SAMPLES[code]
        return {'language_code': code, 'source_id': 'synthetic-approved-test',
                'source_sha256': 'a' * 64,
                'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                'tokens': [text]}

    @staticmethod
    def _record(code, form, features):
        return {'language_code': code, 'lemma_id': code + ':toy:1',
                'sense_id': code + ':toy:sense:1', 'lemma': form, 'form': form,
                'features': features, 'source_id': 'synthetic-approved-test',
                'evidence_version': 'test-only-v1'}

    @classmethod
    def _approved(cls, code):
        sample = SAMPLES[code]
        form = ('اردو' if code == 'ur' else sample)
        features = {'case': 'oblique'} if code == 'ur' else {'number': 'singular'}
        return {'sources': [{
            'id': 'synthetic-approved-test', 'languages': [code],
            'sha256': 'a' * 64, 'release_approved': True,
            'rights_status': 'APPROVED', 'reviewed_by': 'synthetic-test-reviewer',
            'rights_evidence_sha256': 'b' * 64,
            'reviewed_records': {
                'morphology': [p.evidence_digest(cls._record(code, form, features))],
                'segmentation': [p.evidence_digest(cls._segment(code))],
                'orthographic_relation': [],
            },
        }]}


if __name__ == '__main__':
    unittest.main()
