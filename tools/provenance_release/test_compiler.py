import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.provenance_release.compiler import compile_release

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()

class TestCompiler(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

        self.output_manifest = self.root / 'release_provenance.json'
        self.output_notice = self.root / 'NOTICE.txt'

        # Setup files
        self.src = self.put('evidence/upstream.json', b'{"word":"test"}')
        self.lic = self.put('evidence/upstream-license.txt', b'Mock Publisher CC0-1.0 license text')
        self.pack = self.put('packs/fixture.pack.gz', b'{"entries": 1}')
        self.notice = self.put('notices/attribution.txt', b'mock-source Mock Publisher CC0-1.0 https://example.com')

        self.source = {
            'source_id': 'mock-source',
            'kind': 'dictionary',
            'origin_url': 'https://example.com',
            'publisher': 'Mock Publisher',
            'dataset_version': 'v1',
            'retrieval': {
                'identity': 'mock-snapshot',
                'url': 'https://example.com/data',
                'date': '2025-01-01',
                'artifact_path': 'evidence/upstream.json',
                'sha256': sha256_file(self.root / self.src)
            },
            'license': {
                'id': 'CC0-1.0',
                'evidence_url': 'https://example.com/license',
                'evidence_path': 'evidence/upstream-license.txt',
                'evidence_sha256': sha256_file(self.root / self.lic)
            },
            'status': 'APPROVED_FOR_REDISTRIBUTION',
            'review': {'reviewer': 'test-reviewer', 'decision_url': 'https://example.com/review'},
            'alterations': ['none']
        }

        self.candidate = {
            'asset_id': 'mock-asset',
            'kind': 'dictionary',
            'artifact_path': 'packs/fixture.pack.gz',
            'sha256': sha256_file(self.root / self.pack),
            'source_refs': [{
                'source_id': 'mock-source',
                'dataset_version': 'v1',
                'artifact_sha256': self.source['retrieval']['sha256']
            }],
            'output_license_id': 'CC0-1.0',
            'compiler_license_id': 'MIT',
            'notices': {'mock-source': 'notices/attribution.txt'},
            'compliance': {},
            'provenance_mode': 'per_record',
            'record_sources': [{'record_id': 'entry-1', 'source_ids': ['mock-source']}],
            'review': {'reviewer': 'test-reviewer', 'decision_url': 'https://example.com/review'}
        }

        self.manifest = {
            'intellectual_property_status': 'MIXED',
            'languages': [],
            'packs': [
                {'pack_file': 'packs/fixture.pack.gz'}
            ]
        }

        self.write_ledger([self.source])
        self.write_daily([self.candidate])
        self.write_manifest(self.manifest)

    def put(self, path: str, content: bytes) -> str:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return path

    def write_ledger(self, sources):
        p = self.root / 'legal/ledger/sources.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'schema_version': '1.0.0', 'sources': sources}))

    def write_daily(self, candidates):
        p = self.root / 'legal/ledger/daily/1.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'schema_version': '1.0.0', 'date': '2025-01-01', 'release_candidates': candidates}))

    def write_manifest(self, manifest):
        p = self.root / 'manifest.json'
        p.write_text(json.dumps(manifest))

    def test_successful_compilation(self):
        compile_release(self.root, self.output_manifest, self.output_notice)

        # Check generated manifest
        self.assertTrue(self.output_manifest.exists())
        data = json.loads(self.output_manifest.read_text())
        self.assertEqual(data['schema_version'], '1.0.0')
        self.assertEqual(len(data['assets']), 1)

        asset = data['assets'][0]
        self.assertEqual(asset['asset_id'], 'mock-asset')
        self.assertEqual(len(asset['provenance']), 1)
        self.assertEqual(asset['provenance'][0]['source_id'], 'mock-source')

        # Check unverified statuses preservation
        self.assertEqual(len(data['unverified_statuses']), 0)

        # Check generated notice
        self.assertTrue(self.output_notice.exists())
        notice = self.output_notice.read_text()
        self.assertIn('Asset: mock-asset', notice)
        self.assertIn('Source: mock-source', notice)
        self.assertIn('Publisher: Mock Publisher', notice)

    def test_altered_files_hash_mismatch(self):
        self.source['retrieval']['sha256'] = '0' * 64
        self.write_ledger([self.source])
        with self.assertRaises(ValueError) as ctx:
            compile_release(self.root, self.output_manifest, self.output_notice)
        self.assertIn('HASH_MISMATCH', str(ctx.exception))

    def test_missing_author_publisher(self):
        del self.source['publisher']
        self.write_ledger([self.source])
        with self.assertRaises(ValueError) as ctx:
            compile_release(self.root, self.output_manifest, self.output_notice)
        self.assertIn('publisher', str(ctx.exception))

    def test_mixed_licensing_conflict(self):
        self.source['license']['id'] = 'CC-BY-SA-4.0'
        self.candidate['output_license_id'] = 'CC0-1.0'
        self.write_ledger([self.source])
        self.write_daily([self.candidate])
        with self.assertRaises(ValueError) as ctx:
            compile_release(self.root, self.output_manifest, self.output_notice)
        self.assertIn('LICENSE_CONFLICT', str(ctx.exception))

    def test_duplicate_provenance(self):
        import copy
        duplicate_source = copy.deepcopy(self.source)
        self.write_ledger([self.source, duplicate_source])
        with self.assertRaises(ValueError) as ctx:
            compile_release(self.root, self.output_manifest, self.output_notice)
        self.assertIn('DUPLICATE', str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
