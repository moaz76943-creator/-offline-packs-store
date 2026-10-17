"""Production auto-seed must refuse missing, altered and unlicensed evidence."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.gha_factory.queue_autoseed import seeder

SID = 'reviewed.fixture'
LANG = 'de'


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


class AdmissionFileTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        source_bytes = b'{"synthetic_fixture_only":true}\n'
        proof_bytes = b'synthetic evidence for a mocked approved source; test only\n'
        part_bytes = b'{"synthetic_partition_only":true}\n'
        self.source_sha = digest(source_bytes)
        self.proof_sha = digest(proof_bytes)
        self.source_path = self.root / 'safe' / 'input.jsonl'
        self.source_path.parent.mkdir(parents=True)
        self.source_path.write_bytes(source_bytes)
        proof_path = self.root / 'safe' / 'review.txt'
        proof_path.write_bytes(proof_bytes)
        self.folder = self.root / 'tools' / 'gha_factory' / 'admission' / 'accepted' / 'synthetic'
        self.folder.mkdir(parents=True)
        self.part_path = self.folder / 'partition-00000000.jsonl'
        self.part_path.write_bytes(part_bytes)
        self.source = {
            'source_id': SID, 'kind': 'dictionary',
            'status': 'APPROVED_FOR_REDISTRIBUTION',
            'origin_url': 'https://example.org/fixture', 'publisher': 'fixture only',
            'dataset_version': '2026-fixture',
            'retrieval': {'identity': 'synthetic', 'url': 'https://example.org/download',
                          'date': '2026-10-13', 'artifact_path': 'safe/input.jsonl',
                          'sha256': self.source_sha},
            'license': {'id': 'CC0-1.0', 'evidence_url': 'https://example.org/license-source',
                        'evidence_path': 'safe/review.txt', 'evidence_sha256': self.proof_sha},
            'review': {'reviewer': 'test-fixture', 'decision_url': 'https://example.org/decision'},
            'alterations': ['none, synthetic test only']
        }
        self.job = {'source_id': SID, 'language': LANG, 'dataset_version': '2026-fixture',
                    'category': 'dictionary', 'path': self.part_path.name,
                    'sha256': digest(part_bytes), 'record_count': 1, 'partition_index': 0}
        self.report = {'source_id': SID, 'language': LANG, 'dataset_version': '2026-fixture',
                       'source_artifact_sha256': self.source_sha,
                       'license_evidence_sha256': self.proof_sha,
                       'status': 'ACCEPTED_FOR_QUEUE', 'publication_approved': False}
        # Real Route05 adapter output envelope, but entirely synthetic test data.
        from tools.gha_factory.admission import pipeline
        self.row = {
            'source_id': SID, 'dataset_version': self.source['dataset_version'],
            'language': LANG, 'license_id': self.source['license']['id'],
            'source_artifact_sha256': self.source_sha,
            'license_evidence_sha256': self.proof_sha,
            'source_line': 1, 'source_line_sha256': digest(source_bytes),
            'excluded_categories': [],
            'content': {'word': 'Haus', 'pos': 'noun', 'senses': ['house']},
        }
        self.part_path.write_bytes(pipeline.canon(self.row))
        self.job['sha256'] = digest(self.part_path.read_bytes())
        self.job['license_id'] = self.source['license']['id']
        self.job['license_evidence_sha256'] = self.proof_sha
        self.job['resume_id'] = 'srcadm1-' + digest(
            pipeline.canon([self.source_sha, self.job]))[:40]
        self.key = (SID, LANG, self.source_sha, 0)
        self.ctx = {'languages': frozenset((LANG,)), 'sources': [self.source],
                    'admissions': {self.key: {'folder': self.folder, 'report': self.report, 'job': self.job}}}
        ledger = self.root / 'legal' / 'ledger' / 'sources.json'
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({'schema_version': '1.0.0', 'sources': [self.source]}), encoding='utf-8')

    def tasks(self):
        checked = seeder.verified_context(self.ctx, self.root)
        return seeder.plan(checked, 'b' * 64, [])

    def test_exact_sha_bound_source_license_and_partition_are_eligible(self):
        self.assertEqual(len(self.tasks()), 1)

    def test_source_snapshot_missing_is_not_enqueued(self):
        self.source_path.unlink()
        self.assertEqual(self.tasks(), [])

    def test_source_snapshot_tampering_is_not_enqueued(self):
        self.source_path.write_bytes(b'modified\n')
        self.assertEqual(self.tasks(), [])

    def test_unapproved_licensing_status_is_not_enqueued(self):
        self.source['status'] = 'REVIEW_REQUIRED'
        self.assertEqual(self.tasks(), [])

    def test_unsupported_license_is_not_enqueued(self):
        self.source['license']['id'] = 'GFDL-1.3-only'
        self.assertEqual(self.tasks(), [])

    def test_missing_or_corrupted_license_proof_is_not_enqueued(self):
        (self.root / 'safe' / 'review.txt').write_bytes(b'changed proof\n')
        self.assertEqual(self.tasks(), [])

    def test_partition_missing_is_not_enqueued(self):
        self.part_path.unlink()
        self.assertEqual(self.tasks(), [])

    def test_partition_hash_changed_is_not_enqueued(self):
        self.part_path.write_bytes(b'forged partition\n')
        self.assertEqual(self.tasks(), [])

    def test_bad_dataset_version_is_not_enqueued(self):
        self.report['dataset_version'] = 'wrong'
        self.assertEqual(self.tasks(), [])

    def test_invalid_partition_path_is_not_enqueued(self):
        self.job['path'] = '../../safe/input.jsonl'
        self.assertEqual(self.tasks(), [])

    def test_evidence_source_ids_are_bound_to_report(self):
        self.report['source_id'] = 'different.source'
        self.assertEqual(self.tasks(), [])


    def test_digest_matching_partition_with_wrong_record_identity_is_blocked(self):
        self.row['source_id'] = 'another.approved.source'
        from tools.gha_factory.admission import pipeline
        self.part_path.write_bytes(pipeline.canon(self.row))
        self.job['sha256'] = digest(self.part_path.read_bytes())
        # Recompute the descriptor's bound resume identity: hash alone is not evidence.
        self.job['resume_id'] = 'srcadm1-' + digest(pipeline.canon([
            self.source_sha, {k: v for k, v in self.job.items() if k != 'resume_id'}
        ]))[:40]
        self.assertEqual(self.tasks(), [])

    def test_matching_digest_with_wrong_record_count_is_blocked(self):
        self.job['record_count'] = 2
        self.assertEqual(self.tasks(), [])

    def test_partition_license_identity_must_match_reviewed_source(self):
        self.job['license_evidence_sha256'] = 'f' * 64
        self.assertEqual(self.tasks(), [])

    def test_exact_job_resume_identity_is_required(self):
        self.job['resume_id'] = 'srcadm1-' + '0' * 40
        self.assertEqual(self.tasks(), [])


if __name__ == '__main__':
    unittest.main()
