import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from validate import DirectedPairsContractError, validate, verify_compatible
from sqlite_v2 import build, check_mapping_version

HERE = Path(__file__).parent

def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))

class DirectedPairsSchemaTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture()

    def test_positive(self):
        self.assertIs(validate(self.data), self.data)

    def test_negative_fixture_rejected(self):
        with self.assertRaises(DirectedPairsContractError):
            validate(fixture('negative'))

    def test_fixture_cannot_pass_publication_gate(self):
        with self.assertRaises(DirectedPairsContractError):
            validate(self.data, publication=True)

    def test_stable_identity_compatibility(self):
        changed = copy.deepcopy(self.data)
        changed['directed_pairs'][0]['source_text'] = 'banks'
        self.assertTrue(verify_compatible(self.data, changed))
        changed['directed_pairs'][0]['source_sense_id'] = 'sense.en.riverbank.1'
        with self.assertRaises(DirectedPairsContractError):
            verify_compatible(self.data, changed)

    def test_duplicate_pair_id(self):
        draft = copy.deepcopy(self.data)
        draft['directed_pairs'].append(draft['directed_pairs'][0])
        with self.assertRaises(DirectedPairsContractError):
            validate(draft)

class SqliteMappingTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'directed_pairs.sqlite'

    def test_sqlite_v2_roundtrip_and_compatibility(self):
        build(self.data, self.db)
        with sqlite3.connect(self.db) as con:
            self.assertTrue(check_mapping_version(con))
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM directed_pairs').fetchone()[0], len(self.data['directed_pairs']))

            for row in self.data['directed_pairs']:
                decoded = json.loads(con.execute('SELECT payload_json FROM directed_pairs WHERE pair_id=?', (row['pair_id'],)).fetchone()[0])
                self.assertEqual(decoded, row)

    def test_unknown_migration_is_rejected(self):
        build(self.data, self.db)
        with sqlite3.connect(self.db) as con:
            con.execute('PRAGMA user_version=1')
            with self.assertRaises(DirectedPairsContractError):
                check_mapping_version(con)

if __name__ == '__main__':
    unittest.main()
