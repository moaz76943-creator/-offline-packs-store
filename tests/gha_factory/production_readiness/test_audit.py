"""Small synthetic fixtures; never approved content or production packages."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tools.gha_factory.production_readiness.audit import inspect

ARTIFACT = b'{"synthetic":true}\n'
LICENSE = b'synthetic license evidence'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def create(root, approved=False, accepted=False, packs=0, evidence=True):
    source = {'kind': 'dictionary', 'status': 'APPROVED_FOR_REDISTRIBUTION', 'source_id': 'synthetic'}
    if approved and evidence:
        (root / 'evidence').mkdir(parents=True, exist_ok=True)
        (root / 'evidence/artifact.jsonl').write_bytes(ARTIFACT)
        (root / 'evidence/license.txt').write_bytes(LICENSE)
        source.update({
            'dataset_version': 'v1',
            'origin_url': 'https://example.org/source',
            'publisher': 'TEST ONLY',
            'alterations': ['synthetic fixture'],
            'retrieval': {
                'identity': 'fixture', 'url': 'https://example.org/source.jsonl',
                'date': '2026-10-13', 'artifact_path': 'evidence/artifact.jsonl',
                'sha256': digest(ARTIFACT)},
            'license': {
                'id': 'CC0-1.0', 'evidence_url': 'https://example.org/license',
                'evidence_path': 'evidence/license.txt', 'evidence_sha256': digest(LICENSE)},
            'review': {'reviewer': 'TEST ONLY', 'decision_url': 'https://example.org/review'},
        })
    data = {
        'catalog/language_registry.v1.json': {
            'schema_version': '1.0.0', 'languages': [{'id': f'x{i:03d}'} for i in range(100)]},
        'legal/ledger/sources.json': {
            'schema_version': '1.0.0', 'sources': ([source] if approved else [])},
        'manifest.json': {'total_languages': 100, 'packs': [{'test_only': True}] * packs},
    }
    for name, content in data.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content), encoding='utf-8')
    if accepted:
        job = {
            'source_id': 'synthetic', 'language': 'x000', 'dataset_version': 'v1',
            'category': 'dictionary', 'path': 'partition-00000000.jsonl',
            'sha256': 'a' * 64, 'record_count': 1, 'partition_index': 0,
        }
        p = root / 'tools/gha_factory/admission/accepted/synthetic/queue.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            'schema_version': '1.0.0', 'status': 'ACCEPTED_FOR_QUEUE',
            'publication_approved': False, 'source_id': 'synthetic', 'language': 'x000',
            'dataset_version': 'v1', 'source_artifact_sha256': digest(ARTIFACT),
            'jobs': [job]}), encoding='utf-8')


class ReadinessTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_empty_ledger_reports_source_blocker_not_success(self):
        create(self.root)
        result = inspect(self.root, {'registry_validate', 'admission_partition_verify'})
        self.assertEqual(result['status'], 'BLOCKED_SOURCE')
        self.assertEqual(result['canonical_language_count'], 100)
        self.assertIn('NO_APPROVED_DICTIONARY_SOURCE', result['blockers'])
        self.assertIn('QUEUE_SUPPORTS_VERIFICATION_NOT_PRODUCTION', result['blockers'])

    def test_declared_source_without_partitions_still_blocked(self):
        create(self.root, approved=True)
        result = inspect(self.root, {'registry_validate', 'admission_partition_verify'})
        self.assertEqual(result['status'], 'BLOCKED_PIPELINE')
        self.assertIn('NO_ADMITTED_SOURCE_PARTITIONS', result['blockers'])

    def test_partitions_do_not_imply_lexical_production(self):
        create(self.root, approved=True, accepted=True)
        result = inspect(self.root, {'registry_validate', 'admission_partition_verify'})
        self.assertEqual(result['status'], 'BLOCKED_PIPELINE')
        self.assertEqual(result['admission_manifest_partition_count_unverified'], 1)
        self.assertIsNone(result['actual_production_records_verified'])

    def test_production_tasks_still_require_real_qa(self):
        create(self.root, approved=True, accepted=True, packs=1)
        result = inspect(self.root, {'registry_validate', 'source_backed_real_worker'})
        self.assertEqual(result['status'], 'REQUIRES_PRODUCTION_QA')
        self.assertEqual(result['published_pack_manifest_entries_unverified'], 1)
        self.assertFalse(result['actual_production_worker_result_verified'])

    def test_unrecognised_worker_type_is_not_claimed_to_be_verified(self):
        create(self.root, approved=True, accepted=True)
        report = inspect(self.root, {'registry_validate', 'unknown_worker'})
        self.assertEqual(report['status'], 'BLOCKED_PIPELINE')
        self.assertIn('QUEUE_SUPPORTS_VERIFICATION_NOT_PRODUCTION', report['blockers'])
        self.assertNotIn('PRODUCTION_WORKER_RESULT_NOT_VERIFIED', report['blockers'])
        self.assertFalse(report['actual_production_worker_result_verified'])

    def test_declaration_without_evidence_stays_blocked_source(self):
        create(self.root, approved=True, evidence=False)
        result = inspect(self.root, {'registry_validate', 'admission_partition_verify'})
        self.assertEqual(result['status'], 'BLOCKED_SOURCE')
        self.assertIn('NO_APPROVED_DICTIONARY_SOURCE', result['blockers'])

    def test_stale_license_evidence_stays_blocked_source(self):
        create(self.root, approved=True, accepted=True)
        (self.root / 'evidence/license.txt').write_bytes(b'stale evidence')
        result = inspect(self.root, {'source_backed_real_worker'})
        self.assertEqual(result['status'], 'BLOCKED_SOURCE')
        self.assertIn('NO_APPROVED_DICTIONARY_SOURCE', result['blockers'])

    def test_malformed_jobs_are_not_admitted_partitions(self):
        create(self.root, approved=True, accepted=True)
        path = self.root / 'tools/gha_factory/admission/accepted/synthetic/queue.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        report['jobs'] = [{}]
        path.write_text(json.dumps(report), encoding='utf-8')
        result = inspect(self.root, {'source_backed_real_worker'})
        self.assertEqual(result['admission_manifest_partition_count_unverified'], 0)
        self.assertEqual(result['status'], 'BLOCKED_PIPELINE')
        self.assertIn('NO_ADMITTED_SOURCE_PARTITIONS', result['blockers'])

    def test_duplicate_languages_fail_closed(self):
        create(self.root)
        p = self.root / 'catalog/language_registry.v1.json'
        obj = json.loads(p.read_text())
        obj['languages'][1]['id'] = obj['languages'][0]['id']
        p.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            inspect(self.root, {})

    def test_invalid_release_manifest_fails_closed(self):
        create(self.root)
        (self.root / 'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'manifest'):
            inspect(self.root, {})

    def test_read_json_rejects_symlinked_parent_before_opening(self):
        # Synthetic external fixture: a parent symlink must not be followed.
        from tools.gha_factory.production_readiness.audit import read_json
        with tempfile.TemporaryDirectory() as external:
            (Path(external) / 'metadata.json').write_text('{"synthetic":true}', encoding='utf-8')
            (self.root / 'catalog').symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'unsafe|symlink'):
                read_json(self.root, 'catalog/metadata.json')

    def test_read_json_rejects_absolute_and_traversal_paths(self):
        from tools.gha_factory.production_readiness.audit import read_json
        (self.root / 'safe.json').write_text('{"synthetic":true}', encoding='utf-8')
        (self.root / 'nested').mkdir()
        for relative in ('nested/../safe.json', str(self.root / 'safe.json')):
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    read_json(self.root, relative)

    def test_oversize_registry_fails_closed(self):
        create(self.root)
        p = self.root / 'catalog/language_registry.v1.json'
        p.write_text(' ' * 2_000_001)
        with self.assertRaisesRegex(ValueError, 'oversized'):
            inspect(self.root, {})


if __name__ == '__main__':
    unittest.main()
