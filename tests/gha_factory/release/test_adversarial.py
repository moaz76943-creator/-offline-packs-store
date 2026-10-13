"""Tampered SQLite, provenance and signing contract regression tests."""
import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_candidate
from tools.gha_factory.release import candidate as rc


class AdversarialTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_candidate.CandidateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def tamper_database(self, sql):
        envelope=self.fixture.sample()
        row=next(x for x in envelope['files'] if x['path']=='content/content.sqlite')
        sqlite_file=self.root/'tampered.sqlite'
        sqlite_file.write_bytes(base64.b64decode(row['contentBase64']))
        with sqlite3.connect(sqlite_file) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute(sql)
            db.commit()
        data=sqlite_file.read_bytes()
        row['contentBase64']=base64.b64encode(data).decode()
        meta=next(x for x in envelope['files'] if x['path']=='metadata/pack.json')
        info=next(x for x in envelope['files'] if x['path']=='content/content.json')
        content=json.loads(base64.b64decode(info['contentBase64']))
        content['sqliteSha256']=rc.digest(data)
        info_bytes=rc.json_bytes(content)
        info['contentBase64']=base64.b64encode(info_bytes).decode()
        metadata=json.loads(base64.b64decode(meta['contentBase64']))
        metadata['contentSha256']=rc.digest(data)
        metadata['contentMetadataSha256']=rc.digest(info_bytes)
        meta['contentBase64']=base64.b64encode(rc.json_bytes(metadata)).decode()
        return self.fixture.archive(envelope)

    def test_missing_mandatory_index_fails_despite_valid_sha(self):
        archive=self.tamper_database('DROP INDEX idx_lexicon_surface')
        with self.assertRaisesRegex(rc.ReleaseError,'indexes'):
            rc.inspect_archive(archive,'de',allow_fixture=True)

    def test_foreign_key_corruption_fails_despite_valid_sha(self):
        archive=self.tamper_database("UPDATE senses SET lexeme_id='nonexistent'")
        with self.assertRaisesRegex(rc.ReleaseError,'foreign_key_check'):
            rc.inspect_archive(archive,'de',allow_fixture=True)

    def test_corrupt_fts_entries_fail_despite_valid_sha(self):
        archive=self.tamper_database('DELETE FROM lexicon_fts')
        with self.assertRaisesRegex(rc.ReleaseError,'FTS5'):
            rc.inspect_archive(archive,'de',allow_fixture=True)

    def test_mismatched_source_provenance_fails(self):
        envelope=self.fixture.sample()
        info=next(x for x in envelope['files'] if x['path']=='content/content.json')
        obj=json.loads(base64.b64decode(info['contentBase64']))
        obj['sourceIds']=['different-source']
        info['contentBase64']=base64.b64encode(rc.json_bytes(obj)).decode()
        meta=next(x for x in envelope['files'] if x['path']=='metadata/pack.json')
        m=json.loads(base64.b64decode(meta['contentBase64']))
        m['contentMetadataSha256']=rc.digest(rc.json_bytes(obj))
        meta['contentBase64']=base64.b64encode(rc.json_bytes(m)).decode()
        with self.assertRaisesRegex(rc.ReleaseError,'provenance'):
            rc.inspect_archive(self.fixture.archive(envelope),'de',allow_fixture=True)


if __name__=='__main__': unittest.main()
