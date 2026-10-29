"""Run: python3 -m unittest discover -s standards/lexical -p 'test_*.py' -v"""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from validate import LexicalContractError, validate, verify_compatible
from sqlite_v2 import build, check_mapping_version, sort_key

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
        # 1. Modifying unpinned lexeme field is valid
        changed['lexemes'][0]['surface']='Häuschen'
        self.assertTrue(verify_compatible(self.data,changed))

        # 2. Modifying unpinned sense field is valid
        changed_sense = copy.deepcopy(self.data)
        changed_sense['senses'][0]['definition'] = 'A new definition'
        self.assertTrue(verify_compatible(self.data, changed_sense))

        # 3. document_id mismatch raises LexicalContractError
        changed_doc = copy.deepcopy(self.data)
        changed_doc['document_id'] = 'doc.other'
        with self.assertRaisesRegex(LexicalContractError, 'document_id changed'):
            verify_compatible(self.data, changed_doc)

        # 4. Lexeme removal raises LexicalContractError
        removed_lexeme = copy.deepcopy(self.data)
        # we need to remove the first lexeme, but it's lex.de.haus.
        # it is used in sense.de.haus, which is used in translations and examples.
        # To avoid schema validation errors during `verify_compatible`, we can remove everything using it,
        # or we just let it fail on "orphan sense", but `verify_compatible` calls `validate(updated)`.
        # To strictly test verify_compatible's logic for removal, we should remove it, and all its references,
        # BUT verify_compatible expects validate(updated) to pass.
        # wait, if we remove all its references, validate(updated) will pass!
        removed_lexeme['lexemes'].pop(0)
        removed_lexeme['senses'] = [s for s in removed_lexeme['senses'] if s['lexeme_id'] != 'lex.de.haus']
        removed_lexeme['translations'] = [t for t in removed_lexeme['translations'] if 'sense.de.haus' not in (t['from_sense_id'], t['to_sense_id'])]
        removed_lexeme['examples'] = [e for e in removed_lexeme['examples'] if e['sense_id'] != 'sense.de.haus']
        with self.assertRaisesRegex(LexicalContractError, 'breaking removal'):
            verify_compatible(self.data, removed_lexeme)

        # 5. Sense removal raises LexicalContractError
        removed_sense = copy.deepcopy(self.data)
        removed_sense['senses'].pop(0)
        removed_sense['translations'] = [t for t in removed_sense['translations'] if 'sense.de.haus' not in (t['from_sense_id'], t['to_sense_id'])]
        removed_sense['examples'] = [e for e in removed_sense['examples'] if e['sense_id'] != 'sense.de.haus']
        with self.assertRaisesRegex(LexicalContractError, 'breaking removal'):
            verify_compatible(self.data, removed_sense)

        # Modifying pinned lexeme fields raises LexicalContractError ('language', 'script', 'lemma', 'pos')
        # lemma (existing)
        changed['lexemes'][0]['lemma']='Häuschen'
        with self.assertRaises(LexicalContractError):verify_compatible(self.data,changed)

        # language
        changed_lang = copy.deepcopy(self.data)
        changed_lang['lexemes'][0]['language'] = 'fr'
        # To bypass example language mismatch and test `verify_compatible`, we remove the example
        changed_lang['examples'] = [e for e in changed_lang['examples'] if e['example_id'] != 'ex.de.haus']
        with self.assertRaisesRegex(LexicalContractError, 'stable identity reassignment'):
            verify_compatible(self.data, changed_lang)

        # script
        changed_script = copy.deepcopy(self.data)
        changed_script['lexemes'][0]['script'] = 'Arab'
        with self.assertRaisesRegex(LexicalContractError, 'stable identity reassignment'):
            verify_compatible(self.data, changed_script)

        # pos
        changed_pos = copy.deepcopy(self.data)
        changed_pos['lexemes'][0]['pos'] = 'noun' if changed_pos['lexemes'][0]['pos'] != 'noun' else 'verb'
        with self.assertRaisesRegex(LexicalContractError, 'stable identity reassignment'):
            verify_compatible(self.data, changed_pos)

        # Modifying pinned sense fields raises LexicalContractError ('lexeme_id', 'concept_id')
        # lexeme_id
        changed_sense_lex = copy.deepcopy(self.data)
        changed_sense_lex['senses'][0]['lexeme_id'] = changed_sense_lex['senses'][1]['lexeme_id']
        with self.assertRaisesRegex(LexicalContractError, 'stable identity reassignment'):
            verify_compatible(self.data, changed_sense_lex)

        # concept_id
        changed_concept = copy.deepcopy(self.data)
        changed_concept['senses'][0]['concept_id'] = 'concept.other'
        with self.assertRaisesRegex(LexicalContractError, 'stable identity reassignment'):
            verify_compatible(self.data, changed_concept)

        with self.assertRaises(LexicalContractError):verify_compatible(self.data,{'contract_version':'9.0.0'})


class SqliteMappingTest(unittest.TestCase):
    def setUp(self):
        self.data=fixture()
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=self.root/'lexical.sqlite'

    def test_sqlite_v2_roundtrip_fts_and_compatibility_views(self):
        build(self.data,self.db)
        with sqlite3.connect(self.db) as con:
            self.assertTrue(check_mapping_version(con))
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM lexemes').fetchone()[0],len(self.data['lexemes']))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM examples').fetchone()[0],len(self.data['examples']))
            self.assertEqual(con.execute("SELECT pos FROM lexicon WHERE id='lex.de.gehen'").fetchone()[0],'verb')
            self.assertEqual(con.execute("SELECT COUNT(*) FROM lexicon_fts WHERE lexicon_fts MATCH 'Haus'").fetchone()[0],1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM lexicon_fts WHERE lexicon_fts MATCH 'بيت' AND language_code='ar'").fetchone()[0],1)
            for row in self.data['lexemes']:
                loaded=json.loads(con.execute('SELECT fields_json FROM lexicon WHERE id=?',(row['lexeme_id'],)).fetchone()[0])
                self.assertEqual(loaded,row)
            for table,pk,entries in [('senses','sense_id','senses'),('translations','translation_id','translations'),('examples','example_id','examples')]:
                for row in self.data[entries]:
                    decoded=json.loads(con.execute(f'SELECT payload_json FROM {table} WHERE {pk}=?',(row[pk],)).fetchone()[0])
                    self.assertEqual(decoded,row)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM translations').fetchone()[0],5)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM translations WHERE from_sense_id='sense.ar.bayt'").fetchone()[0],0)

    def test_deterministic_reordering_no_overwrite(self):
        build(self.data,self.db)
        initial=hashlib.sha256(self.db.read_bytes()).hexdigest()
        shuffled=copy.deepcopy(self.data)
        for key in ('lexemes','senses','translations','examples','relations'):
            shuffled[key].reverse()
        alternate=self.root/'other.sqlite'
        build(shuffled,alternate)
        self.assertEqual(initial,hashlib.sha256(alternate.read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):build(self.data,self.db)

    def test_unknown_migration_is_rejected(self):
        build(self.data,self.db)
        with sqlite3.connect(self.db) as con:
            con.execute('PRAGMA user_version=1')
            with self.assertRaises(LexicalContractError):check_mapping_version(con)

    def test_unicode_sort_preserves_diacritics(self):
        self.assertEqual(sort_key('HÄUSER'),'häuser')
        self.assertEqual(sort_key('بَيْت'),'بَيْت')


if __name__=='__main__':
    unittest.main()
