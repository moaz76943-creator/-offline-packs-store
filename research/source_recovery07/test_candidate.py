"""Narrow checks for a historical real-data research candidate; NOT legal admission."""
import hashlib
import json
import sqlite3
import unittest
from pathlib import Path

PATH = Path(__file__).with_name('lexeme_L2957_candidate.json')

class TestWikidataCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PATH.read_bytes()
        cls.doc = json.loads(cls.raw)
        cls.row = cls.doc['lexemes'][0]

    def test_evidence_not_promoted(self):
        self.assertEqual(self.doc['admission_status'], 'REVIEW_REQUIRED')
        self.assertFalse(self.doc['release_ready'])
        self.assertFalse(self.doc['original_json_artifact_verified'])
        self.assertIsNone(self.doc['original_json_artifact_sha256'])
        self.assertIsNone(self.doc['original_license_notice_sha256'])

    def test_fixed_original_revision(self):
        rev = self.doc['source_revision']
        self.assertEqual(rev, 2321564793)
        self.assertIn(f'revision={rev}', self.doc['canonical_entity_api'])
        self.assertIn(f'oldid={rev}', self.doc['source_url'])
        self.assertEqual(self.row['language_code'], 'de')
        self.assertEqual(self.row['language_item'], 'Q188')

    def test_stable_record_ids(self):
        self.assertRegex(self.row['id'], r'^L[1-9][0-9]*$')
        for name, part in [('forms', 'F'), ('senses', 'S')]:
            ids = [i['id'] for i in self.row[name]]
            self.assertEqual(len(ids), len(set(ids)))
            for item_id in ids:
                self.assertRegex(item_id, rf'^{self.row["id"]}-{part}[1-9][0-9]*$')

    def test_no_unsupported_claims_or_media(self):
        self.assertIsNone(self.row['translation_ar'])
        self.assertIsNone(self.row['cefr_level'])
        for k in ('example_sentences', 'audio_files', 'images'):
            self.assertEqual(self.row[k], [])

    def test_minimal_sqlite_mapping_smoke_not_full_contract(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.executescript('CREATE TABLE lexicon (id TEXT PRIMARY KEY, language_code TEXT, surface TEXT);'
                           'CREATE TABLE senses (id TEXT PRIMARY KEY, lexeme_id TEXT NOT NULL REFERENCES lexicon(id));'
                           'CREATE TABLE forms (id TEXT PRIMARY KEY, lexeme_id TEXT NOT NULL REFERENCES lexicon(id), surface TEXT);')
        rid = 'wikidata:' + self.row['id']
        conn.execute('INSERT INTO lexicon VALUES(?,?,?)', (rid, 'de', self.row['lemma']))
        for s in self.row['senses']:
            conn.execute('INSERT INTO senses VALUES(?,?)', ('wikidata:'+s['id'], rid))
        for f in self.row['forms']:
            conn.execute('INSERT INTO forms VALUES(?,?,?)', ('wikidata:'+f['id'], rid, f['text']))
        self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(conn.execute('SELECT count(*) FROM forms').fetchone()[0], 8)
        conn.close()

    def test_local_derived_bytes_hashable_not_original(self):
        self.assertEqual(len(hashlib.sha256(self.raw).hexdigest()), 64)
        self.assertNotEqual(self.doc['record_type'], 'IMMUTABLE_ORIGINAL_JSON')

if __name__ == '__main__':
    unittest.main()
