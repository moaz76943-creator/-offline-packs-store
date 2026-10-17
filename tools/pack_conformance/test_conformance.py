import unittest
import os
import json
import sqlite3
import unicodedata
import gzip
import base64
from pathlib import Path
import tempfile
import io

from tools.pack_conformance import conformance
from tools.pack_v2 import pipeline

def make_dummy_envelope(language, db_bytes):
    counts = {'lexicon': 1, 'concepts': 1, 'senses': 1, 'translations': 0, 'examples': 0, 'lexical_relations': 0, 'grammar': 0}
    info = {
        'contractVersion': pipeline.CONTRACT,
        'schemaVersion': pipeline.MAPPING,
        'documentId': 'doc1',
        'languageCode': language,
        'languagesPresent': [language],
        'tableCounts': counts,
        'sqliteSha256': pipeline.sha(db_bytes),
        'sourceIds': ['src1'],
        'fixtureOnly': True,
    }
    info_bytes = (pipeline.compact(info) + '\n').encode()

    manifest = {
        'packId': language,
        'languageCode': language,
        'version': conformance.check.VERSION,
        'contractVersion': pipeline.CONTRACT,
        'schemaVersion': pipeline.MAPPING,
        'format': pipeline.FORMAT,
        'contentRows': counts['lexicon'],
        'contentSha256': pipeline.sha(db_bytes),
        'contentMetadataSha256': pipeline.sha(info_bytes),
        'sourceIds': ['src1'],
        'fixtureOnly': True,
    }
    meta_bytes = (pipeline.compact(manifest) + '\n').encode()
    content = {'content/content.json': info_bytes, 'content/content.sqlite': db_bytes, 'metadata/pack.json': meta_bytes}
    envelope = {
        'packId': language, 'version': conformance.check.VERSION, 'contractVersion': pipeline.CONTRACT,
        'schemaVersion': pipeline.MAPPING, 'format': pipeline.FORMAT,
        'files': [{'path': p, 'contentBase64': base64.b64encode(content[p]).decode('ascii')} for p in pipeline.FILES]
    }
    raw = (pipeline.compact(envelope) + '\n').encode()

    sink = io.BytesIO()
    with gzip.GzipFile(fileobj=sink, mode='wb', filename='', mtime=0, compresslevel=9) as zip_file:
        zip_file.write(raw)
    return sink.getvalue()

def create_valid_db_bytes(language):
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        path = tf.name
    try:
        with sqlite3.connect(path) as db:
            db.executescript(pipeline.DDL)
            db.execute("INSERT INTO metadata VALUES ('contract_version', ?)", (pipeline.CONTRACT,))
            db.execute("INSERT INTO metadata VALUES ('mapping_version', ?)", (pipeline.MAPPING,))
            db.execute("INSERT INTO metadata VALUES ('document_id', 'doc1')")
            db.execute("INSERT INTO metadata VALUES ('language_code', ?)", (language,))
            db.execute("INSERT INTO schema_migrations VALUES (?, 'public v2 lexical mapping')", (pipeline.MAPPING,))

            db.execute("INSERT INTO concepts VALUES ('con-123')")

            surf = "test"
            lemma = "test"
            sort_key = unicodedata.normalize('NFKC', surf).casefold()

            src = {"source_id": "src1", "publisher": "p1", "origin_url": "https://example.com/es", "dataset_version": "1.0", "retrieval_id": "r1", "license_id": "PUBLIC-DOMAIN", "record_locator": "r1", "fixture_only": True, "publication_approved": False}
            fields = {
                "lexeme_id": "lex-123", "language": language, "script": "Latn", "lemma": lemma, "surface": surf,
                "pos": "noun", "direction": "ltr", "source": src
            }
            db.execute('''INSERT INTO lexicon(id, surface, part_of_speech, pos, direction, language_code, script, dialect, sort_key, cefr_level, frequency_rank, fields_json, source_json)
                          VALUES(?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?, ?)''',
                       ("lex-123", surf, "noun", "noun", "ltr", language, "Latn", sort_key, json.dumps(fields), json.dumps(src)))
            rowid = db.execute("SELECT rowid FROM lexicon WHERE id='lex-123'").fetchone()[0]

            sense_src = {"source_id": "src1", "publisher": "p1", "origin_url": "https://example.com/es", "dataset_version": "1.0", "retrieval_id": "r1", "license_id": "PUBLIC-DOMAIN", "record_locator": "r1", "fixture_only": True, "publication_approved": False}
            sense_fields = {"sense_id": "sen-123", "lexeme_id": "lex-123", "concept_id": "con-123", "definition": "test def", "source": sense_src}
            db.execute('''INSERT INTO senses(sense_id, lexeme_id, concept_id, definition, payload_json)
                          VALUES('sen-123', 'lex-123', 'con-123', 'test def', ?)''', (json.dumps(sense_fields),))

            db.execute("INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code) VALUES(?, ?, ?, ?, ?)",
                       (rowid, surf, lemma, "test def", language))
            db.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")

            db.execute('PRAGMA user_version=2')
            db.commit()
        with open(path, 'rb') as f:
            return f.read()
    finally:
        os.unlink(path)

class TestConformance(unittest.TestCase):
    def setUp(self):
        self.root = Path('.')
        self.language = "es"

    def test_valid(self):
        db_bytes = create_valid_db_bytes(self.language)
        archive = make_dummy_envelope(self.language, db_bytes)
        res = conformance.check_conformance(archive, self.language, self.root)
        self.assertEqual(res['status'], 'FIXTURE_QUARANTINED')
        self.assertIn('actual_counts', res)

    def test_invalid_fts5(self):
        db_bytes = create_valid_db_bytes(self.language)
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(db_bytes)
            tf.flush()
            with sqlite3.connect(tf.name) as db:
                db.execute("UPDATE lexicon_fts SET gloss='wrong'")
                db.commit()
            with open(tf.name, 'rb') as f:
                bad_db = f.read()
        os.unlink(tf.name)
        archive = make_dummy_envelope(self.language, bad_db)
        res = conformance.check_conformance(archive, self.language, self.root)
        self.assertEqual(res['status'], 'FAIL')
        self.assertEqual(res['error_code'], 'FTS5_CORRUPT')

    def test_invalid_pos(self):
        db_bytes = create_valid_db_bytes(self.language)
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(db_bytes)
            tf.flush()
            with sqlite3.connect(tf.name) as db:
                row = db.execute("SELECT fields_json FROM lexicon WHERE id='lex-123'").fetchone()[0]
                data = json.loads(row)
                data['pos'] = 'fake_pos'
                db.execute("UPDATE lexicon SET fields_json=?, part_of_speech='fake_pos', pos='fake_pos'", (json.dumps(data),))
                db.commit()
            with open(tf.name, 'rb') as f:
                bad_db = f.read()
        os.unlink(tf.name)
        archive = make_dummy_envelope(self.language, bad_db)
        res = conformance.check_conformance(archive, self.language, self.root)
        self.assertEqual(res['status'], 'FAIL')
        self.assertEqual(res['error_code'], 'INVALID_RECEIPT')

    def test_invalid_unicode(self):
        db_bytes = create_valid_db_bytes(self.language)
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(db_bytes)
            tf.flush()
            with sqlite3.connect(tf.name) as db:
                db.execute("UPDATE lexicon SET sort_key='WRONG'")
                db.commit()
            with open(tf.name, 'rb') as f:
                bad_db = f.read()
        os.unlink(tf.name)
        archive = make_dummy_envelope(self.language, bad_db)
        res = conformance.check_conformance(archive, self.language, self.root)
        self.assertEqual(res['status'], 'FAIL')
        self.assertEqual(res['error_code'], 'SQLITE_SCHEMA_MISMATCH')

    def test_missing_provenance(self):
        db_bytes = create_valid_db_bytes(self.language)
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(db_bytes)
            tf.flush()
            with sqlite3.connect(tf.name) as db:
                row = db.execute("SELECT fields_json FROM lexicon WHERE id='lex-123'").fetchone()[0]
                data = json.loads(row)
                del data['source'] # Missing provenance
                db.execute("UPDATE lexicon SET fields_json=?", (json.dumps(data),))
                db.commit()
            with open(tf.name, 'rb') as f:
                bad_db = f.read()
        os.unlink(tf.name)
        archive = make_dummy_envelope(self.language, bad_db)
        res = conformance.check_conformance(archive, self.language, self.root)
        self.assertEqual(res['status'], 'UNVERIFIED')
        self.assertEqual(res['error_code'], 'PROVENANCE_MISSING')
