"""Run: python3 -m unittest discover -s standards/directed_pairs -p 'test_*.py' -v"""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from validate import DirectedPairsContractError
from sqlite_v2 import build, check_mapping_version

HERE = Path(__file__).parent

def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))

class SqliteMappingTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'directed_pairs.sqlite'

    def test_sqlite_v2_roundtrip(self):
        build(self.data, self.db)
        with sqlite3.connect(self.db) as con:
            self.assertTrue(check_mapping_version(con))
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

            # Check data correctly maps without lossy transformations
            count = con.execute('SELECT COUNT(*) FROM directed_translations').fetchone()[0]
            self.assertEqual(count, len(self.data['translations']))

            row = con.execute("SELECT from_sense_id, to_sense_id, source_language, target_language, text, equivalence FROM directed_translations WHERE translation_id='tr.bank_river.es'").fetchone()
            self.assertEqual(row, ('sense.en.bank.1', 'sense.es.orilla.1', 'en', 'es', 'orilla', 'exact'))

            # Check JSON payload
            payload = json.loads(con.execute("SELECT payload_json FROM directed_translations WHERE translation_id='tr.bank_river.es'").fetchone()[0])
            self.assertEqual(payload['from_sense_id'], 'sense.en.bank.1')

    def test_deterministic_reordering_no_overwrite(self):
        build(self.data, self.db)
        initial = hashlib.sha256(self.db.read_bytes()).hexdigest()

        shuffled = copy.deepcopy(self.data)
        shuffled['translations'].reverse()
        alternate = self.root / 'other.sqlite'
        build(shuffled, alternate)
        self.assertEqual(initial, hashlib.sha256(alternate.read_bytes()).hexdigest())

        with self.assertRaises(FileExistsError):
            build(self.data, self.db)

    def test_unknown_migration_is_rejected(self):
        build(self.data, self.db)
        with sqlite3.connect(self.db) as con:
            con.execute('PRAGMA user_version=1')
            with self.assertRaises(DirectedPairsContractError):
                check_mapping_version(con)

if __name__ == '__main__':
    unittest.main()
