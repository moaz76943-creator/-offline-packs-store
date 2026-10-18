"""Synthetic linguistic structures only; never production vocabulary."""
import copy
import json
import unittest
from pathlib import Path
from tools.gha_factory.content_ingestion.normalize import extract, partition, Reject
from standards.lexical.validate import validate

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = json.loads((ROOT/'catalog/language_registry.v1.json').read_text())
SOURCE = {'source_id':'test.synthetic','origin_url':'https://example.org/test',
          'publisher':'TEST ONLY','dataset_version':'fixture-v1',
          'retrieval':{'identity':'fixture','sha256':'a'*64},
          'license':{'id':'CC0-1.0'}}


def row(language='de', word='Testwort'):
    return {'lang_code':language,'word':word,'pos':'noun',
            'senses':[{'glosses':['TEST definition one','TEST elaboration']},
                      {'glosses':['TEST definition two']}]}


def parse(r):
    return extract(r, SOURCE, REGISTRY, r['lang_code'], 'line:1')


class NormalizeTests(unittest.TestCase):
    def test_pilot_languages_contract_and_distinct_senses(self):
        for lang, word in [('de','Testwort'),('ar','اختبار'),('en','Testword'),
                           ('es','Prueba'),('fr','Épreuve')]:
            with self.subTest(lang=lang):
                result = parse(row(lang, word))
                self.assertEqual(len(result['senses']),2)
                self.assertEqual(result['senses'][0]['definition'],'TEST definition one\nTEST elaboration')
                validate(result['document'])
                self.assertFalse(result['lexeme']['source']['publication_approved'])

    def test_source_attested_features_no_article_guess(self):
        r=row();r['tags']=['neuter']
        r['forms']=[{'form':'Testformen','tags':['plural','nominative']},
                    {'form':'Testform','tags':['past','participle','irregular'], 'auxiliary':'haben'},
                    {'form':'das','tags':['definite','article']}]
        r['sounds']=[{'ipa':'/test/','tags':['regional'],'audio':'unsafe.ogg'}]
        result=parse(r);m=result['lexeme']['morphology']
        self.assertEqual(m['gender'],'neuter')
        self.assertEqual(m['articles'][0]['surface'],'das')
        self.assertIn('source',m['inflections'][0])
        self.assertNotIn('audio',result['lexeme']['pronunciations'][0])
        self.assertEqual(len(parse(row())['lexeme'].get('morphology',{}).get('articles',[])),0)

    def test_native_structures_and_turkish_case_preserved(self):
        for lang, word, extra in [('ar','اِخْتِبار',{'root':'خ ب ر','pattern':'افتعال','dialect':'TEST dialect'}),
                                 ('tr','Iİıi',{}),('zh','测试',{}),('ja','テスト',{}),('ko','테스트',{})]:
            r=row(lang,word);r.update(extra);r['forms']=[{'form':word,'tags':['TEST-native-tag']}]
            out=parse(r);self.assertEqual(out['lexeme']['lemma'],word)
            self.assertIn('source_tags',out['lexeme']['morphology']['inflections'][0]['features'])
            self.assertNotIn('articles',out['lexeme']['morphology'])
            validate(out['document'])

    def test_stable_unicode_and_homographs_and_partition(self):
        a=parse(row('fr','Épreuve'));b=parse(row('fr','E\u0301preuve'))
        self.assertEqual(a['lexeme']['lexeme_id'],b['lexeme']['lexeme_id'])
        r=row('fr','Épreuve');r['etymology_number']=2
        self.assertNotEqual(a['lexeme']['lexeme_id'],parse(r)['lexeme']['lexeme_id'])
        lids=[parse(row('en','Test'+str(i)))['lexeme']['lexeme_id'] for i in range(100)]
        parts=[{v for v in lids if partition(v,3)==i} for i in range(3)]
        self.assertEqual(set.union(*parts),set(lids))
        self.assertFalse(parts[0]&parts[1] or parts[1]&parts[2] or parts[0]&parts[2])

    def test_wrong_script_license_and_language(self):
        for change in [{'word':'اختبار'},{'license_id':'CC-BY-NC-4.0'},
                       {'source_id':'other'},{'script':'Arab'},{'word':'\ud800'}]:
            r=row();r.update(change)
            with self.subTest(change=change),self.assertRaises(Reject):parse(r)
        with self.assertRaises(Reject):extract(row('en','Test'),SOURCE,REGISTRY,'de','line:1')

    def test_directed_translation_evidence_unresolved(self):
        r=row();r['senses'][0]['translations']=[{'lang_code':'en','word':'TEST target'}]
        result=parse(r)
        self.assertEqual(result['document']['translations'],[])
        self.assertEqual(result['links'][0]['status'],'REVIEW_REQUIRED_TARGET_SENSE')
        self.assertEqual(result['links'][0]['source_language'],'de')
        self.assertEqual(result['links'][0]['target_language'],'en')

    def test_ambiguous_gender_not_silently_selected(self):
        r=row();r['tags']=['masculine','feminine']
        result=parse(r)
        self.assertNotIn('gender',result['lexeme'].get('morphology',{}))
        self.assertIn('AMBIGUOUS_GENDER',result['review'])

    def test_all_registry_metadata_no_readiness_claim(self):
        self.assertEqual(len(REGISTRY['languages']),100)
        self.assertEqual(len({r['id'] for r in REGISTRY['languages']}),100)
        for entry in REGISTRY['languages']:
            self.assertIn(entry['default_script'],entry['scripts'])
            self.assertIn(entry['default_script'],REGISTRY['scripts'])

    def test_top_level_translations_do_not_guess_source_sense(self):
        r=row();r['translations']=[{'lang_code':'en','word':'TEST target','sense':'TEST ambiguous source'}]
        result=parse(r)
        self.assertEqual(result['document']['translations'],[])
        self.assertIsNone(result['links'][0]['from_sense_id'])
        self.assertEqual(result['links'][0]['status'],'REVIEW_REQUIRED_SOURCE_AND_TARGET_SENSE')

    def test_equal_gloss_different_qualifier_remains_distinct(self):
        r=row();r['senses']=[{'glosses':['TEST same'],'tags':['figurative']},
                            {'glosses':['TEST same'],'tags':['literal']}]
        self.assertEqual(len(parse(r)['senses']),2)
