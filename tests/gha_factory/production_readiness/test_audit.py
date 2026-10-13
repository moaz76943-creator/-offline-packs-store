"""Small synthetic fixtures; never approved content or production packages."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.gha_factory.production_readiness.audit import inspect


def create(root, approved=False, accepted=False, packs=0):
    data = {
        'catalog/language_registry.v1.json': {
            'schema_version': '1.0.0', 'languages': [{'id': f'x{i:03d}'} for i in range(100)]},
        'legal/ledger/sources.json': {
            'schema_version': '1.0.0', 'sources': ([{'kind': 'dictionary',
                'status': 'APPROVED_FOR_REDISTRIBUTION', 'source_id': 'synthetic'}] if approved else [])},
        'manifest.json': {'total_languages': 100, 'packs': [{'test_only': True}] * packs},
    }
    for name, content in data.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content), encoding='utf-8')
    if accepted:
        p = root / 'tools/gha_factory/admission/accepted/synthetic/queue.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'schema_version': '1.0.0',
            'status': 'ACCEPTED_FOR_QUEUE', 'publication_approved': False,
            'jobs': [{'synthetic': True}]}), encoding='utf-8')


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
        result = inspect(self.root, {'registry_validate', *['lexical_ingest', 'morphology_ingest',
            'examples_ingest', 'sqlite_compile', 'pack_release']})
        self.assertEqual(result['status'], 'REQUIRES_PRODUCTION_QA')
        self.assertEqual(result['published_pack_manifest_entries_unverified'], 1)

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

    def test_oversize_registry_fails_closed(self):
        create(self.root)
        p = self.root / 'catalog/language_registry.v1.json'
        p.write_text(' ' * 2_000_001)
        with self.assertRaisesRegex(ValueError, 'oversized'):
            inspect(self.root, {})


if __name__ == '__main__':
    unittest.main()
