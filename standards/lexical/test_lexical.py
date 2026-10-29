"""Run: python3 -m unittest discover -s standards/lexical -p 'test_*.py' -v"""
import copy
import json
import unittest
from pathlib import Path

from validate import LexicalContractError, validate, verify_compatible

HERE = Path(__file__).parent


def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))


class LexicalSchemaTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture()

    def test_positive_five_writing_systems_and_morphologies(self):
        self.assertIs(validate(self.data), self.data)
        self.assertEqual({r['language'] for r in self.data['lexemes']}, {'de','ar','en','es','fr'})
        self.assertEqual(len([x for x in self.data['senses'] if x['lexeme_id']=='lex.de.bank']),2)
        self.assertEqual(len([x for x in self.data['lexemes'] if x['surface']=='bank']),2)
        self.assertTrue(any(x['script']=='Arab' and x['direction']=='rtl' for x in self.data['lexemes']))
        self.assertTrue(any(x.get('morphology',{}).get('conjugations') for x in self.data['lexemes']))

    def test_negative_fixture_rejected(self):
        with self.assertRaises(LexicalContractError):
            validate(fixture('negative'))

    def test_no_invented_cefr_or_mandatory_gender(self):
        draft=copy.deepcopy(self.data)
        for x in draft['senses']:
            x.pop('levels',None)
        for x in draft['lexemes']:
            x.pop('morphology',None)
        validate(draft)

    def test_bad_relations_and_language_mismatch(self):
        for target,field,value in [('translations','to_sense_id','sense.missing'),
                                    ('examples','sense_id','sense.missing'),
                                    ('translations','language','fr')]:
            draft=copy.deepcopy(self.data)
            draft[target][0][field]=value
            with self.subTest(target=target,field=field),self.assertRaises(LexicalContractError):
                validate(draft)

    def test_unsupported_grammar_and_duplicate_ids_rejected(self):
        draft=copy.deepcopy(self.data)
        draft['lexemes'][0]['morphology']['invented_case']='nominative'
        with self.assertRaises(LexicalContractError):validate(draft)
        draft=copy.deepcopy(self.data)
        draft['lexemes'].append(copy.deepcopy(draft['lexemes'][0]))
        with self.assertRaises(LexicalContractError):validate(draft)

    def test_fixture_cannot_pass_publication_gate(self):
        with self.assertRaises(LexicalContractError):validate(self.data,publication=True)

    def test_stable_identity_compatibility(self):
        changed=copy.deepcopy(self.data)
        changed['lexemes'][0]['surface']='Häuschen'
        self.assertTrue(verify_compatible(self.data,changed))
        changed['lexemes'][0]['lemma']='Häuschen'
        with self.assertRaises(LexicalContractError):verify_compatible(self.data,changed)
        with self.assertRaises(LexicalContractError):verify_compatible(self.data,{'contract_version':'9.0.0'})


if __name__=='__main__':
    unittest.main()
