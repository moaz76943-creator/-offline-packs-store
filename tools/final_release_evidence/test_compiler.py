import unittest
import os
import json
import hashlib
import tempfile
import shutil
from pathlib import Path

import jsonschema

from tools.final_release_evidence.compiler import (
    EvidenceCompiler,
    admitted_languages,
    manifest_pack_languages,
)

ROOT = Path(__file__).resolve().parents[2]
LEDGER_SCHEMA = json.loads((ROOT / 'legal/ledger/schema.json').read_text())
DIGEST = 'ab' * 32


def schema_source(source_id, status='APPROVED_FOR_REDISTRIBUTION', dataset_version='1.0.0'):
    """A ledger source the canonical schema accepts. It does not name a language."""
    return {
        'source_id': source_id,
        'kind': 'dictionary',
        'origin_url': 'https://example.com/sources/' + source_id,
        'publisher': 'Example Publisher',
        'author': 'Example Author',
        'dataset_version': dataset_version,
        'retrieval': {
            'identity': source_id,
            'url': 'https://example.com/sources/' + source_id,
            'date': '2026-01-01',
            'artifact_path': 'evidence/' + source_id + '.bin',
            'sha256': DIGEST,
        },
        'license': {
            'id': 'CC0-1.0',
            'evidence_url': 'https://example.com/licenses/' + source_id,
            'evidence_path': 'evidence/' + source_id + '.license',
            'evidence_sha256': DIGEST,
        },
        'status': status,
        'alterations': ['normalized for the offline pack'],
        'review': {
            'reviewer': 'reviewer',
            'decision_url': 'https://github.com/moaz76943-creator/-offline-packs-store/pull/355',
        },
    }


class TestEvidenceCompiler(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.packs_dir = os.path.join(self.test_dir, 'packs')
        os.makedirs(self.packs_dir)

        self.registry_path = os.path.join(self.test_dir, 'registry.json')
        self.manifest_path = os.path.join(self.test_dir, 'manifest.json')
        self.ledger_path = os.path.join(self.test_dir, 'sources.json')
        self.ledger_data = {'schema_version': '1.0.0', 'sources': []}

        self.registry_data = {
            'languages': [
                {'id': 'ar'}, {'id': 'ru'}, {'id': 'de'}, {'id': 'fr'}, {'id': 'es'}
            ]
        }
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry_data, f)

        self.manifest_data = {
            'languages': [
                {'code': 'ar', 'pack_file': 'ar_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'ru', 'pack_file': 'ru_core_a1.pack.gz', 'sha256': 'ru_hash'},
                {'code': 'de', 'pack_file': 'de_core_a1.pack.gz', 'sha256': 'de_hash'},
                {'code': 'fr', 'pack_file': 'fr_core_a1.pack.gz', 'sha256': 'fr_hash'},
            ],
            'packs': [],
        }
        self._write_inputs()

        self.compiler = EvidenceCompiler(
            registry_path=self.registry_path,
            manifest_path=self.manifest_path,
            packs_dir=self.packs_dir,
            ledger_path=self.ledger_path,
        )

    def _write_inputs(self):
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest_data, f)
        with open(self.ledger_path, 'w') as f:
            json.dump(self.ledger_data, f)

    def add_source(self, source_id, status='APPROVED_FOR_REDISTRIBUTION', dataset_version='1.0.0'):
        source = schema_source(source_id, status=status, dataset_version=dataset_version)
        self.ledger_data['sources'].append(source)
        jsonschema.validate(self.ledger_data, LEDGER_SCHEMA)
        self._write_inputs()
        return source

    def publish(self, code, source_id, *, filename=None, sha256='0' * 64, version='1.0.0', extra=None):
        filename = filename or f'{code}-{version}.pack.gz'
        entry = {
            'id': code,
            'languageCode': code,
            'version': version,
            'path': f'packs/{filename}',
            'sha256': sha256,
            'source_ids': [source_id],
        }
        if extra:
            entry.update(extra)
        self.manifest_data['packs'].append(entry)
        self._write_inputs()
        return entry

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_bytes(self, filename, payload=b'published-pack'):
        path = os.path.join(self.packs_dir, filename)
        with open(path, 'wb') as handle:
            handle.write(payload)
        return path

    def compile(self):
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as handle:
            return json.load(handle)

    def test_schema_rejects_language_fields_on_sources(self):
        source = schema_source('src-ar')
        source['languages'] = ['ar']
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({'schema_version': '1.0.0', 'sources': [source]}, LEDGER_SCHEMA)
        source.pop('languages')
        source['language'] = 'ar'
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({'schema_version': '1.0.0', 'sources': [source]}, LEDGER_SCHEMA)

    def test_schema_valid_source_does_not_admit_a_language_by_itself(self):
        self.add_source('src-ar')
        self.assertEqual(admitted_languages(self.ledger_data), set())
        self.assertEqual(admitted_languages(self.ledger_data, self.manifest_data), set())
        res = self.compile()
        self.assertTrue(all(row['status'] in ('metadataOnly', 'licenseBlocked', 'BLOCKED_DEPENDENCY') for row in res['languages'].values()))
        self.assertEqual(res['languages']['ar']['packs'], [])

    def test_language_comes_from_pack_source_provenance(self):
        self.add_source('src-ar')
        self.publish('ar', 'src-ar')
        self.assertEqual(admitted_languages(self.ledger_data, self.manifest_data), {'ar'})
        self.assertNotIn('ru', admitted_languages(self.ledger_data, self.manifest_data))

    def test_forged_language_field_on_a_source_is_ignored(self):
        source = schema_source('src-ar')
        source['languages'] = ['ar']
        self.ledger_data['sources'].append(source)
        self._write_inputs()
        self.assertEqual(admitted_languages(self.ledger_data, self.manifest_data), set())

    def test_review_required_source_does_not_bind_a_pack(self):
        self.add_source('src-ar', status='REVIEW_REQUIRED')
        self.publish('ar', 'src-ar')
        self.assertNotIn('ar', admitted_languages(self.ledger_data, self.manifest_data))
        res = self.compile()
        self.assertEqual(res['languages']['ar']['status'], 'licenseBlocked')
        self.assertEqual(res['languages']['ar']['packs'], [])

    def test_pack_without_matching_source_stays_blocked(self):
        self.publish('ar', 'missing-source')
        self.assertIn('ar', manifest_pack_languages(self.manifest_data))
        self.assertNotIn('ar', admitted_languages(self.ledger_data, self.manifest_data))
        res = self.compile()
        self.assertEqual(res['languages']['ar']['status'], 'licenseBlocked')

    def test_source_ref_dataset_version_must_match(self):
        self.add_source('src-ar', dataset_version='2026-01-01')
        self.publish('ar', 'src-ar', extra={
            'source_ids': None,
            'source_refs': [{
                'source_id': 'src-ar',
                'dataset_version': '1999-01-01',
                'artifact_sha256': DIGEST,
            }],
        })
        self.manifest_data['packs'][-1].pop('source_ids')
        self._write_inputs()
        self.assertNotIn('ar', admitted_languages(self.ledger_data, self.manifest_data))
        self.manifest_data['packs'][-1]['source_refs'][0]['dataset_version'] = '2026-01-01'
        self._write_inputs()
        self.assertIn('ar', admitted_languages(self.ledger_data, self.manifest_data))

    def test_all_registered_ids_processed(self):
        res = self.compile()
        self.assertEqual(res['total_languages'], 5)
        self.assertEqual(len(res['languages']), 5)
        self.assertTrue(all(row['status'] in ('metadataOnly', 'licenseBlocked', 'BLOCKED_DEPENDENCY') for row in res['languages'].values()))

    def test_missing_published_file_is_source_missing(self):
        self.add_source('src-ar')
        self.publish('ar', 'src-ar', filename='ar-1.0.0.pack.gz')
        res = self.compile()
        self.assertEqual(res['languages']['ar']['status'], 'sourceMissing')
        self.assertFalse(res['languages']['ar']['packs'][0]['valid'])

    def test_legacy_glob_does_not_satisfy_a_published_pack(self):
        self.add_source('src-ar')
        self.publish('ar', 'src-ar', filename='ar-1.0.0.pack.gz', sha256='f' * 64)
        legacy = self.write_bytes('ar_core_a1.pack.gz', b'legacy-bytes')
        legacy_hash = hashlib.sha256(b'legacy-bytes').hexdigest()
        self.manifest_data['languages'][0]['sha256'] = legacy_hash
        self.manifest_data['languages'][0]['pack_file'] = 'ar_core_a1.pack.gz'
        self._write_inputs()
        self.assertTrue(os.path.isfile(legacy))
        res = self.compile()
        row = res['languages']['ar']
        self.assertEqual(row['status'], 'sourceMissing')
        self.assertNotEqual(row['status'], 'releaseReady')
        self.assertTrue(all(not pack.get('valid') for pack in row['packs']))
        self.assertNotIn('ar_core_a1.pack.gz', [pack.get('file') for pack in row['packs']])

    def test_sha256_mismatch_on_the_published_path_is_invalid(self):
        self.add_source('src-ru')
        path = self.write_bytes('ru-1.0.0.pack.gz', b'real-bytes')
        actual = self.compiler.compute_sha256(path)
        self.publish('ru', 'src-ru', filename='ru-1.0.0.pack.gz', sha256='0' * 64)
        self.write_bytes('ru_core_a1.pack.gz', b'legacy')
        res = self.compile()
        row = res['languages']['ru']
        self.assertEqual(row['status'], 'invalidPack')
        self.assertTrue(any('sha256' in reason for reason in row['reasons']))
        self.assertNotEqual(row['packs'][0]['actual_sha256'], '0' * 64)
        self.assertEqual(row['packs'][0]['actual_sha256'], actual)
        self.assertFalse(row['packs'][0]['valid'])

    def test_release_ready_only_when_published_path_and_hash_match(self):
        self.add_source('src-ar')
        path = self.write_bytes('ar-1.0.0.pack.gz', b'arabic-published')
        actual = self.compiler.compute_sha256(path)
        self.publish('ar', 'src-ar', filename='ar-1.0.0.pack.gz', sha256=actual)
        self.write_bytes('ar_universal_v1.pack.gz', b'unrelated-legacy')
        res = self.compile()
        row = res['languages']['ar']
        self.assertEqual(row['status'], 'releaseReady')
        self.assertTrue(row['packs'][0]['valid'])
        self.assertEqual(row['packs'][0]['file'], 'packs/ar-1.0.0.pack.gz')
        self.assertEqual(row['packs'][0]['actual_sha256'], actual)
        self.assertEqual(res['languages']['ru']['status'], 'metadataOnly')

    def test_path_escape_is_not_release_ready(self):
        self.add_source('src-ar')
        outside = os.path.join(self.test_dir, 'escaped.pack.gz')
        with open(outside, 'wb') as handle:
            handle.write(b'escaped')
        digest = hashlib.sha256(b'escaped').hexdigest()
        self.publish('ar', 'src-ar', extra={'path': '../escaped.pack.gz', 'sha256': digest})
        res = self.compile()
        self.assertNotEqual(res['languages']['ar']['status'], 'releaseReady')
        self.assertFalse(res['languages']['ar']['packs'][0]['valid'])

    def test_fail_closed_no_overwrite(self):
        output_path = os.path.join(self.test_dir, 'out.json')
        with open(output_path, 'w') as handle:
            json.dump({'original': True}, handle)
        self.compiler.load_manifest_document = lambda: (_ for _ in ()).throw(Exception('Force fail'))
        with self.assertRaises(Exception):
            self.compiler.compile(output_path)
        with open(output_path, 'r') as handle:
            self.assertTrue(json.load(handle).get('original'))
        self.assertFalse(os.path.exists(output_path + '.tmp'))

    def test_committed_evidence_requires_bound_pack(self):
        evidence = json.loads((ROOT / 'tools/final_release_evidence/release_evidence.json').read_text())
        ledger = json.loads((ROOT / 'legal/ledger/sources.json').read_text())
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        jsonschema.validate(ledger, LEDGER_SCHEMA)
        admitted = admitted_languages(ledger, manifest)
        published = manifest_pack_languages(manifest)
        languages = evidence['languages']
        self.assertEqual(evidence['total_languages'], len(languages))
        for code, row in languages.items():
            packs = row.get('packs') or []
            if row.get('status') == 'releaseReady' or any(pack.get('valid') for pack in packs):
                self.assertIn(code, admitted, f'{code} is release-ready without a bound approved source')
                self.assertIn(code, published, f'{code} is release-ready without a manifest pack')
        if not ledger.get('sources') and not manifest.get('packs'):
            self.assertEqual(admitted, set())
            self.assertTrue(all(row.get('status') in ('BLOCKED_DEPENDENCY', 'metadataOnly', 'licenseBlocked') for row in languages.values()))
            self.assertTrue(all(row.get('packs') == [] for row in languages.values()))


if __name__ == '__main__':
    unittest.main()
