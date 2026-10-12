"""Neutral consumer conformance/negative tests for the canonical envelope."""
import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import (FILES, check_envelope, check_sqlite, compact, sha, DDL,
                      make_database, validate_document, grammar_records)

# Import fixtures without relying on tests or source files outside temp dirs.
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_store_pipeline import fixture_doc


class NeutralConsumerFixtureTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root=Path(d.name)
        self.doc=fixture_doc('de')
        self.db=self.root/'local.sqlite'
        self.counts=make_database(self.doc,'de',[],self.db)

    def valid_envelope(self):
        raw=self.db.read_bytes()
        info={'languageCode':'de','tableCounts':self.counts,'sqliteSha256':sha(raw)}
        info_raw=(compact(info)+'\n').encode()
        meta={'languageCode':'de','contentSha256':sha(raw),'contentMetadataSha256':sha(info_raw),
              'contentRows':self.counts['lexicon']}
        parts={'content/content.json':info_raw,'content/content.sqlite':raw,
               'metadata/pack.json':(compact(meta)+'\n').encode()}
        env={'packId':'de','schemaVersion':'2.0.0','format':'json-gzip-v1',
             'files':[{'path':k,'contentBase64':base64.b64encode(parts[k]).decode()} for k in FILES]}
        return env

    def test_neutral_consumer_reads_mandatory_members(self):
        out=check_envelope((compact(self.valid_envelope())+'\n').encode(),'de')
        self.assertEqual(set(out),set(FILES))

    def test_missing_envelope_file_is_rejected(self):
        env=self.valid_envelope()
        env['files']=[p for p in env['files'] if p['path']!='content/content.json']
        with self.assertRaisesRegex(ValueError,'mandatory envelope'):
            check_envelope(compact(env).encode(),'de')

    def test_tampered_sqlite_hash_is_rejected(self):
        env=self.valid_envelope()
        env['files'][1]['contentBase64']=base64.b64encode(b'not SQLite').decode()
        with self.assertRaisesRegex(ValueError,'hash'):
            check_envelope(compact(env).encode(),'de')

    def test_wrong_language_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'identity'):
            check_envelope(compact(self.valid_envelope()).encode(),'fr')

    def test_missing_fts5_is_rejected(self):
        with sqlite3.connect(self.db) as con:
            con.execute('DROP TABLE lexicon_fts')
        with self.assertRaises(sqlite3.OperationalError):
            check_sqlite(self.db,'de')

    def test_wrong_or_oversized_record_fails(self):
        self.doc['lexemes'][0]['lemma']='x'*70000
        with self.assertRaisesRegex(ValueError,'row size'):
            validate_document(self.doc,'de',self.root,True)

    def test_grammatical_sidecar_rejects_wrong_language(self):
        file=self.root/'de.grammar.json'
        file.write_text(json.dumps({'contract_version':'1.0.0','languageCode':'ar','rules':[]}))
        with self.assertRaisesRegex(ValueError,'language'):
            grammar_records(file,'de',True,self.root)

if __name__=='__main__': unittest.main()
