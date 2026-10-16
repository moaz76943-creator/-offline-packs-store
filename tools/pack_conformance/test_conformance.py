import unittest
from pathlib import Path
import json
import gzip
import tempfile
import sqlite3
import base64
import sys
import hashlib

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from tools.pack_conformance.conformance import run_conformance
from tools.pack_v2.pipeline import compile_pack, check_envelope, compact, sha, make_database, MAX_ROW, DDL, CONTRACT, MAPPING, FORMAT, VERSION
from tools.gha_factory.release import candidate
from tools.gha_factory.pack_conformance import check

# Provide a mock fixture_doc
def fixture_doc(lang):
    source = {
        'source_id': 'fixture_src',
        'origin_url': 'https://example.com/test',
        'publisher': 'Test Publisher',
        'dataset_version': '1.0',
        'retrieval_id': '20230101',
        'license_id': 'CC0-1.0',
        'record_locator': 'test_rec_1',
        'artifact_sha256': 'a'*64,
        'publication_approved': False,
        'fixture_only': True
    }
    return {
        'document_id': f'test_doc_{lang}',
        'lexemes': [
            {'lexeme_id': f'lex_{lang}_1', 'surface': 'test', 'lemma': 'test', 'pos': 'noun', 'direction': 'ltr', 'language': lang, 'script': 'Latn', 'source': source}
        ],
        'senses': [
            {'sense_id': f'sense_{lang}_1', 'lexeme_id': f'lex_{lang}_1', 'concept_id': 'concept_1', 'definition': 'test definition', 'source': source}
        ],
        'translations': [],
        'examples': [],
        'relations': [],
        'fixture_only': True
    }

class TestPackConformance(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.root = Path(self.d.name)

        self.doc = fixture_doc('de')
        self.db_path = self.root / 'local.sqlite'

    def _create_pack(self, counts, data, sources, doc, manifest_override=None, info_override=None):
        info = {
            'contractVersion': CONTRACT, 'schemaVersion': MAPPING, 'documentId': doc['document_id'],
            'languageCode': 'de', 'languagesPresent': sorted({r['language'] for r in doc['lexemes']}),
            'tableCounts': counts, 'sqliteSha256': sha(data), 'sourceIds': ['fixture_src'],
            'fixtureOnly': True,
        }
        if info_override:
            info.update(info_override)

        info_bytes = (compact(info)+'\n').encode()

        manifest={
            'packId': 'de', 'languageCode': 'de', 'version': VERSION, 'contractVersion': CONTRACT,
            'schemaVersion': MAPPING, 'format': FORMAT, 'contentRows': counts['lexicon'],
            'contentSha256': sha(data), 'contentMetadataSha256': sha(info_bytes),
            'sourceIds': ['fixture_src'], 'fixtureOnly': True,
        }
        if manifest_override:
            manifest.update(manifest_override)

        meta_bytes = (compact(manifest)+'\n').encode()

        content = {'content/content.json': info_bytes, 'content/content.sqlite': data, 'metadata/pack.json': meta_bytes}
        envelope = {
            'packId': 'de', 'version': VERSION, 'contractVersion': CONTRACT,
            'schemaVersion': MAPPING, 'format': FORMAT,
            'files': [{'path': p, 'contentBase64': base64.b64encode(content[p]).decode('ascii')} for p in ('content/content.json', 'content/content.sqlite', 'metadata/pack.json')]
        }
        raw = (compact(envelope)+'\n').encode()

        pack_path = self.root / 'de.pack.gz'
        with gzip.GzipFile(pack_path, 'wb') as f:
            f.write(raw)
        return pack_path

    def test_valid_pack(self):
        counts = make_database(self.doc, 'de', [], self.db_path)
        data = self.db_path.read_bytes()
        source = self.doc['lexemes'][0]['source']
        sources = {compact(source): source}
        pack_path = self._create_pack(counts, data, sources, self.doc)

        report = run_conformance(pack_path)
        self.assertEqual(report['status'], 'FIXTURE_QUARANTINED')

    def test_invalid_hash(self):
        counts = make_database(self.doc, 'de', [], self.db_path)
        data = self.db_path.read_bytes()
        source = self.doc['lexemes'][0]['source']
        sources = {compact(source): source}
        pack_path = self._create_pack(counts, data, sources, self.doc)

        with self.assertRaises(check.ConformanceError) as cm:
            run_conformance(pack_path, expected_sha256='b'*64)
        self.assertEqual(cm.exception.code, 'SOURCE_HASH_MISMATCH')

    def test_corrupt_archive(self):
        corrupt_path = self.root / 'corrupt.pack.gz'
        corrupt_path.write_bytes(b'not a gzip archive')
        with self.assertRaises(check.ConformanceError) as cm:
            run_conformance(corrupt_path)
        self.assertEqual(cm.exception.code, 'ARCHIVE_CORRUPT')

    def test_cross_language_mismatch(self):
        counts = make_database(self.doc, 'de', [], self.db_path)
        # Manually break language constraint in SQLite db
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE lexicon SET language_code = 'fr'")
        conn.commit()
        conn.close()
        data = self.db_path.read_bytes()
        source = self.doc['lexemes'][0]['source']
        sources = {compact(source): source}
        pack_path = self._create_pack(counts, data, sources, self.doc, info_override={'languagesPresent': ['fr']})

        with self.assertRaises(check.ConformanceError) as cm:
            run_conformance(pack_path)
        self.assertEqual(cm.exception.code, 'LANGUAGE_ID_MISMATCH')

    def test_empty_pack(self):
        counts = make_database(self.doc, 'de', [], self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM lexicon")
        conn.execute("DELETE FROM senses")
        conn.execute("DELETE FROM lexicon_fts")
        conn.commit()
        conn.close()
        data = self.db_path.read_bytes()
        counts['lexicon'] = 0
        counts['senses'] = 0
        sources = {}
        pack_path = self._create_pack(counts, data, sources, self.doc, manifest_override={'contentRows': 0})

        with self.assertRaises(check.ConformanceError) as cm:
            run_conformance(pack_path)
        self.assertEqual(cm.exception.code, 'INVALID_RECEIPT')
