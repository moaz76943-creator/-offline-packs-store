"""Offline integration tests: python -m unittest discover -s tools."""
import base64
import gzip
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('compile_store_packs.py')


class StorePipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / 'sources'
        self.sources.mkdir()
        self.packs = self.root / 'packs'
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text('{"languages":[{"code":"de","name":"German","direction":"ltr"}]}')
        self.source = self.sources / 'de.json'
        self.source.write_text(json.dumps({'languageCode':'de', 'lexicon':[
            {'id':'1','surface':'Haus','part_of_speech':'noun',
             'fields_json':{'examples':['Das Haus.']}}]}))

    def invoke(self, *options):
        return subprocess.run([sys.executable, str(SCRIPT), '--source-dir', str(self.sources),
            '--output-dir', str(self.packs), '--manifest', str(self.manifest), *options],
            capture_output=True, text=True, timeout=15)

    def test_dry_run_and_missing_source_fail_closed(self):
        original = self.manifest.read_bytes()
        self.assertEqual(self.invoke('--dry-run').returncode, 0)
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assertFalse(self.packs.exists())
        self.source.unlink()
        self.assertNotEqual(self.invoke('--dry-run').returncode, 0)

    def test_envelope_manifest_views_and_idempotency(self):
        first = self.invoke()
        self.assertEqual(first.returncode, 0, first.stderr)
        packed = (self.packs / 'de-1.0.0.pack.gz').read_bytes()
        envelope = json.loads(gzip.decompress(packed))
        self.assertEqual(envelope['packId'], 'de')
        inner = {part['path']:base64.b64decode(part['contentBase64']) for part in envelope['files']}
        self.assertEqual(set(inner), {'content/content.sqlite', 'metadata/pack.json'})
        database = self.root / 'verify.sqlite'
        database.write_bytes(inner['content/content.sqlite'])
        with sqlite3.connect(database) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM lexemes').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM examples').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM concepts').fetchone()[0], 0)
        entry = json.loads(self.manifest.read_text())['packs'][0]
        self.assertEqual(entry['sha256'], hashlib.sha256(packed).hexdigest())
        self.assertEqual(entry['contentSha256'], hashlib.sha256(inner['content/content.sqlite']).hexdigest())
        self.assertEqual(entry['installedSizeBytes'], sum(len(x) for x in inner.values()))
        previous = self.manifest.read_bytes()
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual(self.manifest.read_bytes(), previous)
        self.assertEqual((self.packs / 'de-1.0.0.pack.gz').read_bytes(), packed)

    def test_canonical_json(self):
        import tools.compile_store_packs as compile_store_packs

        # Test basic formatting and keys sorting
        result = compile_store_packs.canonical_json({"b": 2, "a": 1})
        self.assertEqual(result, b'{"a":1,"b":2}\n')

        # Test ensure_ascii=False
        result_unicode = compile_store_packs.canonical_json({"key": "üñîçøđé"})
        self.assertEqual(result_unicode, '{"key":"üñîçøđé"}\n'.encode('utf-8'))

        # Test separators=(',', ':') (no spaces)
        result_separators = compile_store_packs.canonical_json({"a": 1, "b": 2})
        self.assertEqual(result_separators, b'{"a":1,"b":2}\n')
        self.assertNotIn(b' ', result_separators)

        # Test allow_nan=False
        with self.assertRaises(ValueError):
            compile_store_packs.canonical_json({"a": float('nan')})
        with self.assertRaises(ValueError):
            compile_store_packs.canonical_json({"a": float('inf')})


if __name__ == '__main__':
    unittest.main()
