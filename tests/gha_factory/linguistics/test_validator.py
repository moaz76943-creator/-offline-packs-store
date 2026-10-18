"""Independent GHA-04 contract tests; fixtures are NOT redistributable corpus."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools' / 'gha_factory' / 'linguistics'))
from validator import LinguisticError, audit_stream, classify_answer, shard_for, validate_form


def form(lang='de', word='Bücher', **kw):
    x = {'language_code': lang, 'lemma_id': lang + ':book:1',
         'sense_id': lang + ':book:meaning', 'lemma': 'Buch', 'form': word,
         'features': {'number': 'plural', 'case': 'nominative'} if lang == 'de' else {},
         'source_id': 'fixture-evidence', 'evidence_version': 'fixture-1'}
    x.update(kw)
    return x


class LinguisticsTests(unittest.TestCase):
    def test_german_noun_case_and_gender(self):
        self.assertTrue(validate_form(form(features={'number':'plural','case':'dative','grammatical_gender':'neuter'}), {'de'}, pos='noun'))
        with self.assertRaises(LinguisticError):
            validate_form(form(features={'case':'instrumental'}), {'de'}, pos='noun')
        with self.assertRaises(LinguisticError):
            validate_form(form(features={'grammatical_gender':'common'}), {'de'}, pos='noun')

    def test_irregular_german_verb_does_not_create_auxiliary(self):
        v=form(word='gegangen', lemma='gehen', features={'verb_form':'past_participle'})
        self.assertTrue(validate_form(v, {'de'}, pos='verb'))
        self.assertNotIn('auxiliary', v)
        with self.assertRaises(LinguisticError):
            validate_form({**v,'auxiliary':'sein'}, {'de'}, pos='verb')

    def test_spanish_french_person_and_compounds(self):
        for lang, word, tense in [('es','he hablado','present_perfect'),('fr',"j'ai mangé",'passe_compose')]:
            x=form(lang, word, features={'tense':tense,'person':'first','number':'singular'}, lemma='manger')
            self.assertTrue(validate_form(x, {lang}, pos='verb'))
            with self.assertRaises(LinguisticError):
                validate_form({**x,'features':{**x['features'],'person':'fourth'}},{lang},pos='verb')

    def test_arabic_root_and_broken_plural_no_generation(self):
        x=form('ar','كُتُب',lemma='كِتَاب',root='ك-ت-ب', features={'number':'plural'},processes=['broken_plural'])
        self.assertTrue(validate_form(x,{'ar'},pos='noun'))
        with self.assertRaises(LinguisticError):
            validate_form({**x,'root':'k-t-b'},{'ar'},pos='noun')

    def test_cjk_and_turkic_not_forced_into_german_rules(self):
        for lang, word in [('zh','学校'),('ja','学生'),('tr','kitaplar'),('sw','watoto')]:
            self.assertTrue(validate_form(form(lang,word), {lang}))

    def test_non_german_number_categories_are_not_globally_forbidden(self):
        self.assertTrue(validate_form(form('sw','watoto',features={'number':'collective'}), {'sw'}))
        self.assertTrue(validate_form(form('ar','كِتَابَان',features={'number':'dual'}), {'ar'}))

    def test_language_id_unicode_and_extra_field_fail_closed(self):
        with self.assertRaises(LinguisticError):
            validate_form(form('de', 'Bücher'), {'ar'})
        with self.assertRaises(LinguisticError):
            validate_form(form('de','bad\x00'),{'de'})
        with self.assertRaises(LinguisticError):
            validate_form({**form(),'level':'A1'},{'de'})
        with self.assertRaises(LinguisticError):
            validate_form({**form(),'lemma_id':'ar:book:1'},{'de'})

    def test_bidi_format_controls_are_rejected_but_joiners_preserved(self):
        # Synthetic Unicode QA, not a licensed linguistic attestation.
        for value in ('Buch\u202e', 'Buch\u2067', 'Buch\u200f', 'Buch\ufeff'):
            with self.subTest(value=repr(value)):
                with self.assertRaises(LinguisticError):
                    validate_form(form(word=value), {'de'})
        with self.assertRaises(LinguisticError):
            validate_form(form(features={'variant':'x\u202e'}), {'de'})
        self.assertTrue(validate_form(form('hi', 'क्\u200dष', lemma='क्\u200dष'), {'hi'}))

    def test_nfc_equivalent_answers_do_not_become_spelling_errors(self):
        expected = form(word='Café', features={})
        self.assertEqual('correct', classify_answer('Cafe\u0301', expected))
        self.assertEqual('spelling_error', classify_answer('Cafe', expected))
        alternate = form(word='Été', features={'number':'singular'})
        self.assertEqual('morphology_error', classify_answer('E\u0301té', expected, [alternate]))

    def test_unhashable_morpheme_kinds_fail_closed(self):
        candidate = form(morphemes=[{'surface':'Buch','kind':[], 'position':0}])
        with self.assertRaises(LinguisticError):
            validate_form(candidate, {'de'})

    def test_streaming_reader_must_use_a_bounded_readline(self):
        import io
        from unittest.mock import patch
        raw = (json.dumps(form(), ensure_ascii=False) + '\n').encode('utf-8')
        class CheckedStream:
            def __init__(self):
                self.data = io.BytesIO(raw)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.data.close()
            def __iter__(self):
                raise AssertionError('unbounded file iteration is forbidden')
            def readline(self, size=-1):
                if size < 0 or size > 1_048_577:
                    raise AssertionError('unbounded readline')
                return self.data.readline(size)
        with patch.object(Path, 'open', lambda self, mode='r': CheckedStream()):
            result = audit_stream(Path('synthetic.jsonl'), hashlib.sha256(raw).hexdigest(),
                                  {'de'}, 'fixture-evidence')
        self.assertEqual(1, result['records'])

    def test_spelling_morphology_unverified_and_ambiguity(self):
        expected=form()
        singular=form(word='Buch', features={'number':'singular','case':'nominative'})
        self.assertEqual('correct',classify_answer('Bücher',expected,[singular]))
        self.assertEqual('morphology_error',classify_answer('Buch',expected,[singular]))
        self.assertEqual('spelling_error',classify_answer('Bucher',expected,[singular]))
        self.assertEqual('unverified',classify_answer('Haus',expected,[singular]))
        unrelated=form(word='Buch',sense_id='de:book:different',features={'number':'singular'})
        self.assertEqual('unverified',classify_answer('Buch',expected,[unrelated]))

    def test_shard_is_stable_and_identity_specific(self):
        a=form()
        self.assertEqual(shard_for(a,17),shard_for(dict(a),17))
        self.assertTrue(0<=shard_for(a,17)<17)
        self.assertNotEqual(shard_for(a,2**31),shard_for(form('ar','كتب'),2**31))

    def test_stream_audit_is_qa_only_bounded_and_hashed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'forms.jsonl'
            rows=[form(),form(word='Büchern',features={'number':'plural','case':'dative'}),form('ar','كُتُب',lemma='كتاب',features={'number':'plural'},root='ك-ت-ب')]
            raw=''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows).encode()
            p.write_bytes(raw)
            report=audit_stream(p,hashlib.sha256(raw).hexdigest(),{'de','ar'},'fixture-evidence',shards=5)
            self.assertEqual('QA_ONLY_BLOCKED_SOURCE',report['status'])
            self.assertEqual(3,report['records'])
            self.assertEqual({'ar':1,'de':2},report['languages'])
            self.assertEqual(3,sum(report['shards'].values()))
            with self.assertRaises(LinguisticError):
                audit_stream(p,'0'*64,{'de','ar'},'fixture-evidence')

    def test_stream_rejects_conflicts_duplicate_json_keys_and_line_limit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'forms.jsonl'
            a=form('ar','كُتُب',root='ك-ت-ب')
            b={**a,'root':'ك-ذ-ب'}
            raw=''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in (a,b)).encode()
            p.write_bytes(raw)
            with self.assertRaises(LinguisticError):
                audit_stream(p,hashlib.sha256(raw).hexdigest(),{'ar'},'fixture-evidence')
            raw=b'{"language_code":"de","language_code":"ar"}\n'
            p.write_bytes(raw)
            with self.assertRaises(LinguisticError):
                audit_stream(p,hashlib.sha256(raw).hexdigest(),{'de','ar'},'fixture-evidence')
            with self.assertRaises(LinguisticError):
                audit_stream(p,hashlib.sha256(raw).hexdigest(),{'de','ar'},'fixture-evidence',max_line_bytes=10)

    def test_compound_candidate_not_lexically_asserted(self):
        x=form(word='Krankenhaus',components=['Kranken','haus'])
        self.assertTrue(validate_form(x,{'de'}))
        with self.assertRaises(LinguisticError):
            validate_form({**x,'components':['']},{'de'})


if __name__=='__main__':
    unittest.main()
