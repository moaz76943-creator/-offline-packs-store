"""Run: python3 -m unittest discover -s standards/lexical -p 'test_*.py' -v"""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from validate import LexicalContractError, validate, verify_compatible
from sqlite_v2 import build, check_mapping_version, sort_key, main

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

    def test_build_output_parent_not_found(self):
        with self.assertRaises(FileNotFoundError):
            build(self.data, self.root / 'nonexistent' / 'db.sqlite')

    @patch('sqlite3.connect')
    def test_build_sqlite_integrity_check_failure(self, mock_connect):
        mock_conn = mock_connect.return_value
        # When checking integrity, return an error. Otherwise act somewhat normally.
        def mock_execute(query, *args, **kwargs):
            mock_cursor = unittest.mock.MagicMock()
            if query == 'PRAGMA integrity_check':
                mock_cursor.fetchone.return_value = ('error',)
            elif query == 'PRAGMA foreign_key_check':
                mock_cursor.fetchall.return_value = []
            elif query == 'SELECT rowid FROM lexicon WHERE id=?':
                mock_cursor.fetchone.return_value = (1,)
            return mock_cursor
        mock_conn.execute.side_effect = mock_execute

        with self.assertRaisesRegex(LexicalContractError, 'SQLite integrity check failed'):
            build(self.data, self.db)

    @patch('sqlite3.connect')
    def test_build_sqlite_foreign_key_check_failure(self, mock_connect):
        mock_conn = mock_connect.return_value
        def mock_execute(query, *args, **kwargs):
            mock_cursor = unittest.mock.MagicMock()
            if query == 'PRAGMA integrity_check':
                mock_cursor.fetchone.return_value = ('ok',)
            elif query == 'PRAGMA foreign_key_check':
                mock_cursor.fetchall.return_value = [(1,)]
            elif query == 'SELECT rowid FROM lexicon WHERE id=?':
                mock_cursor.fetchone.return_value = (1,)
            return mock_cursor
        mock_conn.execute.side_effect = mock_execute

        with self.assertRaisesRegex(LexicalContractError, 'SQLite foreign-key check failed'):
            build(self.data, self.db)

    def test_check_mapping_version_invalid_mapping(self):
        build(self.data, self.db)
        with sqlite3.connect(self.db) as con:
            con.execute("DELETE FROM metadata WHERE key='mapping_version'")
            with self.assertRaisesRegex(LexicalContractError, 'unrecognized mapping or contract version; explicit migration required'):
                check_mapping_version(con)

    def test_main_valid(self):
        input_file = self.root / 'input.json'
        input_file.write_text(json.dumps(self.data), encoding='utf-8')
        result = main([str(input_file), str(self.db)])
        self.assertEqual(result, 0)
        self.assertTrue(self.db.exists())

    def test_main_invalid(self):
        missing_file = self.root / 'missing.json'
        result = main([str(missing_file), str(self.db)])
        self.assertEqual(result, 1)


if __name__=='__main__':
    unittest.main()
