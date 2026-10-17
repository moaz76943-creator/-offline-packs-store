"""Regression tests for public-only sharded readiness verification."""
import importlib.util
import hashlib
import sqlite3
from contextlib import closing
from unittest.mock import patch
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
        ledger = {'schema_version': '1.0.0', 'sources': []}
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


    def test_reports_each_language_with_no_unverified_promotion(self):
        report = checker.audit(self.root, shard=0, shards=1)
        self.assertEqual(len(report['language_rows']), 100)
        self.assertEqual(report['language_rows'][0]['status'], 'REGISTERED')
        self.assertEqual(report['language_rows'][0]['source_status'], 'NOT_ATTESTED')
        self.assertEqual(report['directed_pairs'], [])
        self.assertEqual(report['factory_ready_languages'], [])

    def test_forged_source_approval_not_counted(self):
        self.values['legal/ledger/sources.json']['sources'] = [
            {'source_id': 'forged', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]
        self.write_all()
        report = checker.audit(self.root, shard=0, shards=1)
        self.assertEqual(report['source_approved_ids'], 0)
        self.assertEqual(report['source_approval_missing_evidence'], 1)

    def test_unverified_release_claim_rejected_even_if_flags_set(self):
        self.values['legal/ledger/sources.json']['sources'] = [
            {'source_id': 'forged', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]
        self.values['manifest.json']['packs'] = [{'id': 'aa', 'sha256': '0'*64}]
        lang = self.values['manifest.json']['languages'][0]
        lang.update(content_available=True, pack_verified=True, production_ready=True)
        self.write_all()
        with patch.object(checker, '_verify_pack', return_value={'source_ids': ['forged'], 'directed_pairs': []}):
            with self.assertRaisesRegex(checker.AuditError, '(unapproved provenance|false production)'):
                checker.audit(self.root, shard=0, shards=1)

    def test_directions_are_not_implicitly_symmetric(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'directed.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.executescript("""
                    CREATE TABLE lexicon(id TEXT PRIMARY KEY, language_code TEXT);
                    CREATE TABLE senses(sense_id TEXT PRIMARY KEY, lexeme_id TEXT);
                    CREATE TABLE translations(from_sense_id TEXT, to_sense_id TEXT, language_code TEXT);
                    INSERT INTO lexicon VALUES('l1','aa'),('l2','ab');
                    INSERT INTO senses VALUES('s1','l1'),('s2','l2');
                    INSERT INTO translations VALUES('s1','s2','ab');
                """)
            pairs = checker._directed_pairs(database.read_bytes(), {'aa','ab'})
        self.assertEqual(pairs, [{'source_language': 'aa', 'target_language': 'ab',
                                  'verified_count': 1}])

    def test_fixture_package_metadata_is_not_publishable(self):
        metadata = {'sourceIds': ['sample'], 'fixtureOnly': True}
        with self.assertRaisesRegex(checker.AuditError, 'fixture'):
            checker._pack_source_ids(metadata, {'sourceIds': ['sample'], 'fixtureOnly': True})

    def test_duplicate_pack_source_ids_are_rejected(self):
        metadata = {'sourceIds': ['one', 'one'], 'fixtureOnly': False}
        with self.assertRaisesRegex(checker.AuditError, 'source IDs'):
            checker._pack_source_ids(metadata, {'sourceIds': ['one', 'one'], 'fixtureOnly': False})

    def test_positive_approval_never_implies_language_ready(self):
        payload = b'public source bytes'
        rights = b'public license evidence'
        (self.root / 'evidence').mkdir()
        (self.root / 'evidence/source.dat').write_bytes(payload)
        (self.root / 'evidence/license.txt').write_bytes(rights)
        self.values['legal/ledger/sources.json']['sources'] = [{
            'source_id': 'sample', 'status': 'APPROVED_FOR_REDISTRIBUTION',
            'publisher': 'Test publisher', 'dataset_version': '1.0',
            'origin_url': 'https://example.org/content', 'alterations': ['No changes'],
            'retrieval': {'identity': 'snapshot-1', 'url': 'https://example.org/snapshot',
                          'artifact_path': 'evidence/source.dat', 'sha256': hashlib.sha256(payload).hexdigest()},
            'license': {'id': 'CC0-1.0', 'evidence_url': 'https://example.org/rights',
                        'evidence_path': 'evidence/license.txt', 'evidence_sha256': hashlib.sha256(rights).hexdigest()},
            'review': {'reviewer': 'Human', 'decision_url': 'https://example.org/decision'},
        }]
        self.write_all()
        report = checker.audit(self.root, shard=0, shards=1)
        self.assertEqual(report['source_approved_ids'], 1)
        self.assertEqual(report['production_ready_languages'], 0)
        self.assertEqual(report['factory_ready_languages'], [])

    def test_symlinked_approval_proof_is_not_accepted(self):
        (self.root / 'evidence').mkdir()
        (self.root / 'evidence' / 'source.dat').symlink_to(self.root / 'manifest.json')
        source = {'source_id': 'spoof', 'status': 'APPROVED_FOR_REDISTRIBUTION',
                  'publisher': 'Test', 'dataset_version': '1', 'origin_url': 'https://example.org/data',
                  'alterations': ['No changes'],
                  'retrieval': {'identity': 'x', 'url': 'https://example.org/x',
                                'artifact_path': 'evidence/source.dat', 'sha256': '0' * 64},
                  'license': {'id': 'CC0-1.0', 'evidence_url': 'https://example.org/rights',
                              'evidence_path': 'evidence/source.dat', 'evidence_sha256': '0' * 64},
                  'review': {'reviewer': 'Human', 'decision_url': 'https://example.org/decision'}}
        self.values['legal/ledger/sources.json']['sources'] = [source]
        self.write_all()
        self.assertEqual(checker.audit(self.root, shard=0, shards=1)['source_approved_ids'], 0)

    def test_duplicate_approval_identifier_is_rejected(self):
        self.values['legal/ledger/sources.json']['sources'] = [
            {'source_id': 'same', 'status': 'REVIEW_REQUIRED'},
            {'source_id': 'same', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'duplicate provenance'):
            checker.audit(self.root, shard=0, shards=1)


if __name__ == '__main__':
    unittest.main()
