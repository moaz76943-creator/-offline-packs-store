"""Regression tests for public-only sharded readiness verification."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

CHECK_PATH = Path(__file__).resolve().parents[3] / 'tools/gha_factory/coverage_audit/check.py'
spec = importlib.util.spec_from_file_location('coverage_audit', CHECK_PATH)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        ids = [chr(97 + i // 26) + chr(97 + i % 26) for i in range(100)]
        # Synthetic fixtures: only for unit tests, NEVER production packs.
        manifest = {'total_languages': 100, 'packs': [], 'languages': [
            {'code': v, 'registered': True, 'is_active': False,
             'content_available': False, 'pack_verified': False,
             'production_ready': False, 'direction': 'ltr'} for v in ids]}
        registry = {'scripts': {'Latn': {'direction': 'ltr'}},
                    'languages': [{'id': v, 'scripts': ['Latn'], 'default_script': 'Latn'} for v in ids]}
        readiness = {'states': {v: 'unverified' for v in ids}}
        version = {'release_status': 'BLOCKED_DEPENDENCY', 'packs': {}}
        ledger = {'sources': []}
        self.values = {'manifest.json': manifest,
                       'catalog/language_registry.v1.json': registry,
                       'catalog/content_readiness.v1.json': readiness,
                       'version.json': version,
                       'legal/ledger/sources.json': ledger}
        self.write_all()

    def write_all(self):
        for name, value in self.values.items():
            p = self.root / name
            p.parent.mkdir(exist_ok=True, parents=True)
            p.write_text(json.dumps(value), encoding='utf-8')

    def test_all_100_languages_are_partitioned_once(self):
        checks = [checker.audit(self.root, shard=i, shards=10) for i in range(10)]
        self.assertEqual(sum(x['language_count'] for x in checks), 100)
        self.assertEqual(sum(x['verified_v2_packs'] for x in checks), 0)

    def test_false_legacy_activation_fails_closed(self):
        self.values['manifest.json']['languages'][0]['is_active'] = True
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'false production activation'):
            checker.audit(self.root, shard=0, shards=1)

    def test_unapproved_packs_are_rejected(self):
        self.values['manifest.json']['packs'] = [{'id': 'aa'}]
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'empty source'):
            checker.audit(self.root, shard=0, shards=1)

    def test_missing_registered_language_fails(self):
        self.values['catalog/content_readiness.v1.json']['states'].pop('dv')
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'identities'):
            checker.audit(self.root, shard=0, shards=1)

    def test_duplicate_registry_ids_fail(self):
        self.values['catalog/language_registry.v1.json']['languages'][-1]['id'] = 'aa'
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'duplicate'):
            checker.audit(self.root, shard=0, shards=1)

    def test_duplicate_json_keys_fail(self):
        (self.root / 'version.json').write_text('{"packs":{},"packs":{}}', encoding='utf-8')
        with self.assertRaisesRegex(checker.AuditError, 'duplicate JSON key'):
            checker.audit(self.root, shard=0, shards=1)

    def test_malformed_shard_rejected(self):
        with self.assertRaisesRegex(checker.AuditError, 'invalid shard'):
            checker.audit(self.root, shard=10, shards=10)

    def test_approved_ledger_alone_does_not_claim_content(self):
        self.values['legal/ledger/sources.json']['sources'] = [
            {'source_id': 'reviewed-sample', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]
        self.write_all()
        self.assertFalse(checker.audit(self.root, shard=0, shards=1)['production_release_claimed'])


if __name__ == '__main__':
    unittest.main()
