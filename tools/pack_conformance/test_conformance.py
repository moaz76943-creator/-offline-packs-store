import unittest
import sys
import json
import sqlite3
import gzip
import tempfile
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pack_conformance import conformance as check
from tools.pack_v2 import pipeline
from tools.gha_factory.release import candidate

def make_fixture(language='de', modify_db=None, doc_overrides=None, info_overrides=None, meta_overrides=None, env_overrides=None, alter_archive=None):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        import sys
        sys.path.insert(0, str(ROOT / 'tools'))
        from test_store_pipeline import fixture_doc
        doc = fixture_doc(language)
        doc['fixture_only'] = True
        for l in doc['lexemes']:
            l['source']['fixture_only'] = True

        if doc_overrides:
            doc.update(doc_overrides)

        db = root / 'local.sqlite'
        counts = pipeline.make_database(doc, language, [], db)

        if modify_db:
            with sqlite3.connect(db) as conn:
                modify_db(conn)
                conn.commit()
            # Update counts to reflect the potentially modified database
            with sqlite3.connect(db) as conn:
                for table in counts:
                    try:
                        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    except sqlite3.OperationalError:
                        counts[table] = 0

        raw = db.read_bytes()
        info = {'languageCode': language, 'tableCounts': counts, 'sqliteSha256': pipeline.sha(raw), 'fixtureOnly': True, 'contractVersion': pipeline.CONTRACT, 'schemaVersion': '2.0.0', 'documentId': doc['document_id'], "sourceIds": [l['source']['source_id'] for l in doc['lexemes']], 'languagesPresent': [language]}
        if info_overrides:
            info.update(info_overrides)
        info_raw = (pipeline.compact(info) + '\n').encode()

        meta = {'languageCode': language, 'packId': language, 'contentSha256': pipeline.sha(raw), 'contentMetadataSha256': pipeline.sha(info_raw),
              'contentRows': counts['lexicon'], 'contractVersion': pipeline.CONTRACT, 'format': pipeline.FORMAT, 'schemaVersion': '2.0.0', 'version': '1.0.0', 'fixtureOnly': True, "sourceIds": info['sourceIds']}
        if meta_overrides:
            meta.update(meta_overrides)
        meta_raw = (pipeline.compact(meta) + '\n').encode()

        parts = {'content/content.json': info_raw, 'content/content.sqlite': raw, 'metadata/pack.json': meta_raw}

        env = {'packId': language, 'schemaVersion': '2.0.0', 'format': pipeline.FORMAT, 'contractVersion': pipeline.CONTRACT, 'version': '1.0.0',
             'files': [{'path': k, 'contentBase64': base64.b64encode(parts[k]).decode()} for k in pipeline.FILES]}
        if env_overrides:
            env.update(env_overrides)

        uncompressed = pipeline.compact(env).encode()
        if alter_archive:
            uncompressed = alter_archive(uncompressed)

        return gzip.compress(uncompressed, mtime=0)

class TestConformance(unittest.TestCase):
    def test_fixture_valid(self):
        archive = make_fixture('de')
        report = check.inspect(archive, 'de', root=ROOT, allow_fixture=True)
        self.assertEqual(report['status'], 'FIXTURE_QUARANTINED')

    def test_invalid_schema(self):
        with self.assertRaises(check.ConformanceError) as cm:
            def mod(conn):
                conn.execute("DROP TABLE lexicon")
            archive = make_fixture('de', modify_db=mod)
            check.inspect(archive, 'de', root=ROOT, allow_fixture=True)
        self.assertEqual(cm.exception.code, 'SQLITE_SCHEMA_MISMATCH')

    def test_invalid_hash(self):
        with self.assertRaises(candidate.ReleaseError):
            archive = make_fixture('de', meta_overrides={'contentSha256': '0'*64})
            check.inspect(archive, 'de', root=ROOT, allow_fixture=True)

    def test_missing_evidence_status(self):
        res = check.audit(ROOT)
        self.assertEqual(res['status'], 'BLOCKED_SOURCE')

    def test_fts5_execution(self):
        with self.assertRaises(check.ConformanceError) as cm:
            def mod(conn):
                conn.execute("DELETE FROM lexicon_fts")
            archive = make_fixture('de', modify_db=mod)
            check.inspect(archive, 'de', root=ROOT, allow_fixture=True)
        self.assertEqual(cm.exception.code, 'FTS5_CORRUPT')

    def test_mismatched_language(self):
        with self.assertRaises(check.ConformanceError) as cm:
            archive = make_fixture('de')
            check.inspect(archive, 'fr', root=ROOT, allow_fixture=True)
        self.assertEqual(cm.exception.code, 'LANGUAGE_ID_MISMATCH')

if __name__ == '__main__':
    unittest.main()
