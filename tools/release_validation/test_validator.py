"""Synthetic shape fixtures only; NOT public corpus or approved release evidence."""
import base64
import gzip
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from validator import audit, inspect_archive


class ReleaseValidationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'legal/ledger').mkdir(parents=True)
        (self.root / 'tools/sources/pilot5').mkdir(parents=True)
        (self.root / 'legal/ledger/sources.json').write_text('{"schema_version":"1.0.0","sources":[]}')
        (self.root / 'tools/sources/pilot5/blocked_sources.json').write_text('{"status":"BLOCKED_SOURCE"}')
        self.manifest = {'languages': [{'code': c, 'is_active': False, 'production_ready': False} for c in ('de','ar','en','es','fr')], 'packs': [], 'intellectual_property_status':'UNVERIFIED_RIGHTS'}
        self.version = {'latest_version':None,'packs':{},'release_status':'BLOCKED_DEPENDENCY'}
        self.write()

    def write(self):
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))
        (self.root/'version.json').write_text(json.dumps(self.version))

    def test_missing_approved_sources_are_blocked_not_released(self):
        evidence = audit(self.root)
        self.assertEqual(evidence['status'], 'BLOCKED_DEPENDENCY')
        self.assertEqual(evidence['verified_packs'], [])
        self.assertIn('APPROVED_CORPUS_MISSING', evidence['blockers'])

    def test_stale_version_url_fails(self):
        self.version['packs']['de_pack']={'version':'4.0.0','file_url':'https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/packs/de_master.pack.gz'}
        self.write()
        self.assertIn('VERSION_TARGET_MISSING', audit(self.root)['blockers'])

    def test_unverified_legacy_must_not_be_active(self):
        self.manifest['languages'][0]['is_active']=True
        self.manifest['languages'][0]['pack_file']='de_core_a1.pack.gz'
        self.write()
        self.assertIn('UNVERIFIED_LEGACY_ACTIVE', audit(self.root)['blockers'])

    def sample_archive(self):
        db = self.root/'content.sqlite'
        with sqlite3.connect(db) as cn:
            cn.executescript('PRAGMA user_version=2; CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); '
                'CREATE TABLE concepts(concept_id TEXT PRIMARY KEY); '
                'CREATE TABLE lexicon(id TEXT PRIMARY KEY,surface TEXT,language_code TEXT); '
                'CREATE TABLE senses(sense_id TEXT PRIMARY KEY); '
                'CREATE TABLE examples(example_id TEXT PRIMARY KEY); '
                'CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface); '
                "INSERT INTO concepts VALUES('c1'); INSERT INTO lexicon VALUES('l1','Haus','de'); "
                "INSERT INTO senses VALUES('s1'); INSERT INTO examples VALUES('e1'); "
                "INSERT INTO lexicon_fts(surface) VALUES('Haus');")
        parts={'content/content.json':b'{"lexemes":[{"id":"l1"}]}',
            'content/content.sqlite':db.read_bytes(),
            'metadata/pack.json':b'{"packId":"de","version":"1.0.0"}'}
        env={'packId':'de','version':'1.0.0','files':[{'path':k,'contentBase64':base64.b64encode(v).decode()} for k,v in sorted(parts.items())]}
        buf=io.BytesIO()
        with gzip.GzipFile(filename='', mode='wb',mtime=0,fileobj=buf) as f: f.write(json.dumps(env).encode())
        return buf.getvalue(),parts

    def test_real_sqlite_checks_and_hashes(self):
        archive,parts=self.sample_archive()
        result=inspect_archive(archive,'de','1.0.0',hashlib.sha256(parts['content/content.sqlite']).hexdigest())
        self.assertEqual(result['lexemes'], 1)
        self.assertEqual(result['concepts'], 1)
        self.assertEqual(result['examples'], 1)
        self.assertEqual(result['senses'], 1)
        self.assertEqual(result['fts_match'], 'Haus')

    def test_reject_wrong_content_hash(self):
        archive,_=self.sample_archive()
        with self.assertRaisesRegex(ValueError,'content SHA'):
            inspect_archive(archive,'de','1.0.0','0'*64)

    def test_reject_missing_required_envelope_member(self):
        archive,parts=self.sample_archive()
        outer=json.loads(gzip.decompress(archive))
        outer['files']=[x for x in outer['files'] if x['path']!='content/content.json']
        with self.assertRaisesRegex(ValueError,'envelope'):
            inspect_archive(gzip.compress(json.dumps(outer).encode()),'de','1.0.0', hashlib.sha256(parts['content/content.sqlite']).hexdigest())

    def test_gzip_bomb_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(gzip.compress(b'a'*(9*1024*1024)), 'de','1.0.0','0'*64)


if __name__=='__main__':
    unittest.main()
