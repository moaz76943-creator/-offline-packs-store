"""Synthetic fixtures only; no legal approval or production evidence."""
import json
import unittest
from unittest.mock import patch
import test_pipeline as fixtures
sha = fixtures.sha
from tools.gha_factory.admission import pipeline, verified_snapshot as verified


class VerifiedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for key in ('root', 'raw', 'evidence', 'source'):
            setattr(self, key, getattr(self.fixture, key))
        (self.root / 'input/decision.txt').write_bytes(b'Independent fixture decision only.\n')
        self.descriptor = {
            'source_id': self.source['source_id'], 'dataset_version': 'fixture-v1',
            'source_sha256': sha(self.raw), 'license_evidence_sha256': sha(self.evidence),
            **self.source['review'], 'evidence_path': 'input/decision.txt',
            'evidence_sha256': sha(b'Independent fixture decision only.\n')}
        self._descriptor()

    def _descriptor(self):
        path = self.root / 'legal/ledger/review_snapshots/test-owner-fixture.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self.descriptor))

    def run_admit(self, **kwargs):
        return verified.admit_verified(
            repo_root=self.root, source_id=self.source['source_id'],
            input_path=self.root / 'input/raw.jsonl', out_dir=self.root / 'out',
            language='de', dataset_version=kwargs.pop('dataset_version_override', 'fixture-v1'),
            part_size=1, **kwargs)

    def _ledger(self):
        self.fixture._ledger()

    def test_verified_fixture_partitions_without_release_approval(self):
        report = self.run_admit()
        self.assertEqual(report['actual_accepted_records'], 1)
        self.assertFalse(report['publication_approved'])
        job = report['jobs'][0]
        self.assertEqual(job['sha256'], sha((self.root / 'out' / job['path']).read_bytes()))

    def test_unknown_license(self):
        self.source['license']['id'] = 'UNKNOWN'; self._ledger(); self.assert_blocked()

    def test_unapproved_source(self):
        self.source['status'] = 'REVIEW_REQUIRED'; self._ledger(); self.assert_blocked()

    def test_changed_source_hash(self):
        (self.root / 'input/raw.jsonl').write_bytes(self.raw + b'\n'); self.assert_blocked()

    def assert_blocked(self):
        with self.assertRaises(pipeline.AdmissionError):
            self.run_admit()
        self.assertFalse((self.root / 'out').exists())

    def test_legacy_accepts_unhashed_decision_new_entrypoint_rejects(self):
        # Reproduces exact live-main defect before checking the repaired path.
        report = pipeline.admit(repo_root=self.root, source_id=self.source['source_id'],
                                input_path=self.root / 'input/raw.jsonl', out_dir=self.root / 'legacy',
                                language='de', dataset_version='fixture-v1')
        self.assertEqual(report['status'], 'ACCEPTED_FOR_QUEUE')
        (self.root / 'legal/ledger/review_snapshots/test-owner-fixture.json').unlink()
        self.assert_blocked()

    def test_altered_decision_bytes(self):
        (self.root / 'input/decision.txt').write_bytes(b'Forged decision')
        self.assert_blocked()

    def test_descriptor_bindings(self):
        for key in ('source_id', 'dataset_version', 'source_sha256', 'license_evidence_sha256', 'reviewer', 'decision_url'):
            with self.subTest(key=key):
                old = self.descriptor[key]
                self.descriptor[key] = 'different'; self._descriptor()
                self.assert_blocked()
                self.descriptor[key] = old

    def test_missing_decision_file(self):
        (self.root / 'input/decision.txt').unlink(); self.assert_blocked()

    def test_symlink_decision(self):
        (self.root / 'input/alias').symlink_to('decision.txt')
        self.descriptor['evidence_path'] = 'input/alias'; self._descriptor()
        self.assert_blocked()

    def test_symlink_parent(self):
        (self.root / 'alias').symlink_to(self.root / 'input', target_is_directory=True)
        self.descriptor['evidence_path'] = 'alias/decision.txt'; self._descriptor()
        self.assert_blocked()

    def test_rights_conflict_even_with_matching_hash(self):
        raw = b'CC BY-NC-SA 4.0\n'
        (self.root / 'input/license.txt').write_bytes(raw)
        self.source['license']['evidence_sha256'] = sha(raw)
        self.descriptor['license_evidence_sha256'] = sha(raw)
        self._ledger(); self._descriptor(); self.assert_blocked()

    def test_unknown_notice_even_with_matching_hash(self):
        raw = b'Rights unknown\n'
        (self.root / 'input/license.txt').write_bytes(raw)
        self.source['license']['evidence_sha256'] = sha(raw)
        self.descriptor['license_evidence_sha256'] = sha(raw)
        self._ledger(); self._descriptor(); self.assert_blocked()

    def test_source_size_bound(self):
        with patch.object(verified, 'MAX_SOURCE_BYTES', 16):
            self.assert_blocked()

    def test_line_read_is_bounded(self):
        raw = b'x' * (pipeline.MAX_LINE + 1) + b'\n'
        (self.root / 'input/raw.jsonl').write_bytes(raw)
        self.source['retrieval']['sha256'] = sha(raw)
        self.descriptor['source_sha256'] = sha(raw)
        self._ledger(); self._descriptor(); self.assert_blocked()

    def test_original_changes_after_snapshot_do_not_change_admitted_bytes(self):
        original = pipeline.admit
        def mutate_then_admit(**kwargs):
            (self.root / 'input/raw.jsonl').write_bytes(b'forged')
            return original(**kwargs)
        with patch.object(pipeline, 'admit', side_effect=mutate_then_admit):
            report = self.run_admit()
        self.assertEqual(report['source_artifact_sha256'], sha(self.raw))
