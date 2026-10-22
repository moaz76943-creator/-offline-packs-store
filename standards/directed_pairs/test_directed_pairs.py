"""Run: python3 -m unittest discover -s standards/directed_pairs -p 'test_*.py' -v"""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from validate import DirectedPairContractError, validate, verify_compatible
from sqlite_v2 import build, check_mapping_version

HERE = Path(__file__).parent


def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))


class DirectedPairSchemaTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture('positive')

    def test_positive_fixture(self):
        self.assertIs(validate(self.data), self.data)

    def test_negative_fixture_rejected(self):
        with self.assertRaises(DirectedPairContractError):
            validate(fixture('negative'))

    def test_reject_duplicate_pair_id(self):
        draft = copy.deepcopy(self.data)
        draft['pairs'].append(copy.deepcopy(draft['pairs'][0]))
        with self.assertRaises(DirectedPairContractError):
            validate(draft)

    def test_reject_duplicate_direction(self):
        draft = copy.deepcopy(self.data)
        dup = copy.deepcopy(draft['pairs'][0])
        dup['pair_id'] = 'pair.different.id'
        draft['pairs'].append(dup)
        with self.assertRaises(DirectedPairContractError):
            validate(draft)

    def test_fixture_cannot_pass_publication_gate(self):
        with self.assertRaises(DirectedPairContractError):
            validate(self.data, publication=True)

    def test_stable_identity_compatibility(self):
        changed = copy.deepcopy(self.data)
        changed['pairs'][0]['text'] = 'changed'
        self.assertTrue(verify_compatible(self.data, changed))

        changed['pairs'][0]['source_sense_id'] = 'sense.new.1'
        with self.assertRaises(DirectedPairContractError):
            verify_compatible(self.data, changed)

        with self.assertRaises(DirectedPairContractError):
            verify_compatible(self.data, {'contract_version': '9.0.0'})


class SqliteMappingTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture('positive')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'directed.sqlite'

    def test_sqlite_v2_roundtrip_and_compatibility(self):
        build(self.data, self.db)
        with sqlite3.connect(self.db) as con:
            self.assertTrue(check_mapping_version(con))
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM directed_pairs').fetchone()[0], len(self.data['pairs']))

            for row in self.data['pairs']:
                decoded = json.loads(con.execute(f'SELECT payload_json FROM directed_pairs WHERE pair_id=?', (row['pair_id'],)).fetchone()[0])
                self.assertEqual(decoded, row)

    def test_no_overwrite(self):
        build(self.data, self.db)
        with self.assertRaises(FileExistsError):
            build(self.data, self.db)

    def test_unknown_migration_is_rejected(self):
        build(self.data, self.db)
        with sqlite3.connect(self.db) as con:
            con.execute('PRAGMA user_version=1')
            with self.assertRaises(DirectedPairContractError):
                check_mapping_version(con)

if __name__ == '__main__':
    unittest.main()
