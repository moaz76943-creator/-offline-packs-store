"""Run: python3 -m unittest discover -s standards/lexical -p 'test_*.py' -v"""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validate import LexicalContractError
from sqlite_v2 import build, check_mapping_version, sort_key, main

HERE = Path(__file__).parent


def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))


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

    def test_build_raises_file_not_found_error(self):
        missing_dir = self.root / 'missing_dir' / 'output.sqlite'
        with self.assertRaises(FileNotFoundError):
            build(self.data, missing_dir)

    @patch('sqlite3.connect')
    def test_build_cleans_up_on_base_exception(self, mock_connect):
        mock_conn = mock_connect.return_value
        mock_conn.executescript.side_effect = Exception("test error")

        output_file = self.root / 'error_output.sqlite'
        # Do not create the file beforehand because build checks if it exists.
        # Instead, we mock it such that it doesn't exist at first, but is unlinked
        # However, pathlib.Path.unlink(missing_ok=True) does not complain if it's missing.
        # Let's mock unlink to ensure it is called.

        with patch.object(Path, 'unlink') as mock_unlink:
            with self.assertRaisesRegex(Exception, "test error"):
                build(self.data, output_file)

            mock_unlink.assert_called_once_with(missing_ok=True)

        mock_conn.close.assert_called_once()

    @patch('sys.stderr')
    def test_main_success(self, mock_stderr):
        input_file = self.root / 'input.json'
        input_file.write_text(json.dumps(self.data), encoding='utf-8')
        output_file = self.root / 'output.sqlite'

        args = [str(input_file), str(output_file)]
        self.assertEqual(main(args), 0)
        self.assertTrue(output_file.exists())

    @patch('sys.stderr')
    def test_main_failure_invalid_json(self, mock_stderr):
        input_file = self.root / 'input_invalid.json'
        input_file.write_text("invalid json", encoding='utf-8')
        output_file = self.root / 'output_fail.sqlite'

        args = [str(input_file), str(output_file)]
        self.assertEqual(main(args), 1)


if __name__=='__main__':
    unittest.main()
