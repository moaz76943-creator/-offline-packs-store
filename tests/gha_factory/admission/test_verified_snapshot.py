"""Synthetic fixtures only, plus one public CC BY-SA Wikidata copyright notice."""
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_pipeline as fixtures
sha = fixtures.sha
from tools.gha_factory.admission import pipeline, verified_snapshot as verified

WIKIDATA_COPYRIGHT = Path(__file__).with_name('fixtures') / 'Wikidata_Copyright-oldid1523614187.wikitext'
WIKIDATA_COPYRIGHT_SHA256 = 'a74df271d6e2cceb81f71967fb180c66d08c33a670d14d8b64448ee9ef286396'
REPO_DECISION = 'https://github.com/moaz76943-creator/-offline-packs-store/issues/179#issuecomment-1'


class VerifiedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for key in ('root', 'raw', 'evidence', 'source'):
            setattr(self, key, getattr(self.fixture, key))
        (self.root / 'input/decision.txt').write_bytes(b'Independent fixture decision only.\n')
        self.source['review']['decision_url'] = REPO_DECISION
        self.fixture._ledger()
        self.descriptor = {
            'source_id': self.source['source_id'], 'dataset_version': 'fixture-v1',
            'source_sha256': sha(self.raw), 'license_evidence_sha256': sha(self.evidence),
            **self.source['review'], 'evidence_path': 'input/decision.txt',
            'evidence_sha256': sha(b'Independent fixture decision only.\n')}
        self._descriptor()

    def use_notice(self, raw):
        if isinstance(raw, str):
            raw = raw.encode('utf-8')
        (self.root / 'input/license.txt').write_bytes(raw)
        digest = sha(raw)
        self.source['license']['evidence_sha256'] = digest
        self.descriptor['license_evidence_sha256'] = digest
        self._ledger()
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

    def test_decision_url_must_be_an_issue_or_pull_on_this_repository(self):
        for url in (
            'https://example.org/decision/1',
            'https://github.com/other/-offline-packs-store/issues/1',
            'https://github.com/moaz76943-creator/-offline-packs-store',
            'https://github.com/moaz76943-creator/-offline-packs-store/commit/abc',
            'http://github.com/moaz76943-creator/-offline-packs-store/issues/1',
        ):
            with self.subTest(url=url):
                self.source['review']['decision_url'] = url
                self.descriptor['decision_url'] = url
                self._ledger()
                self._descriptor()
                with self.assertRaisesRegex(pipeline.AdmissionError, 'this repository'):
                    self.run_admit()
        self.source['review']['decision_url'] = REPO_DECISION
        self.descriptor['decision_url'] = REPO_DECISION
        self._ledger()
        self._descriptor()

    def test_equivalent_input_path_is_resolved_before_comparison(self):
        report = verified.admit_verified(
            repo_root=self.root, source_id=self.source['source_id'],
            input_path=self.root / 'input' / '..' / 'input' / 'raw.jsonl',
            out_dir=self.root / 'out', language='de', dataset_version='fixture-v1',
            part_size=1)
        self.assertEqual(report['actual_accepted_records'], 1)

    def test_real_wikidata_copyright_notice_satisfies_cc0(self):
        raw = WIKIDATA_COPYRIGHT.read_bytes()
        self.assertEqual(len(raw), 586)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), WIKIDATA_COPYRIGHT_SHA256)
        self.use_notice(raw)
        report = self.run_admit()
        self.assertEqual(report['actual_accepted_records'], 1)

    def test_cc0_wordings_and_public_domain_dedication_are_not_conflicts(self):
        path = self.root / 'input/wording.txt'
        for notice in (
            'Creative Commons CC0 License\n',
            'CC0 1.0 Universal\n',
            'https://creativecommons.org/publicdomain/zero/1.0/\n',
            'CC0 1.0 Universal. The person who associated a work with this deed has dedicated the work to the public domain.\n',
            'Creative Commons CC0 License. Other datasets may be Non-Commercial.\n',
        ):
            with self.subTest(notice=notice):
                path.write_text(notice, encoding='utf-8')
                verified.license_notice(path, 'CC0-1.0')

    def test_public_domain_declaration_still_conflicts_with_cc0_text(self):
        self.use_notice('CC0 1.0 Universal. Dedicated to the public domain.\n')
        self.source['license']['id'] = 'PUBLIC-DOMAIN'
        self.source['license']['public_domain_proof'] = {
            'jurisdiction': 'fixture', 'legal_basis': 'fixture', 'work_date': '1900'}
        self._ledger()
        with self.assertRaisesRegex(pipeline.AdmissionError, 'conflict'):
            self.run_admit()

    def test_license_identifiers_still_conflict_when_prose_words_do_not(self):
        self.use_notice('Creative Commons CC0 License and CC BY-SA 4.0\n')
        with self.assertRaisesRegex(pipeline.AdmissionError, 'conflict'):
            self.run_admit()
        self.use_notice('CC0 License\nall rights reserved\n')
        with self.assertRaisesRegex(pipeline.AdmissionError, 'restricted'):
            self.run_admit()

    def test_original_changes_after_snapshot_do_not_change_admitted_bytes(self):
        original = pipeline.admit
        def mutate_then_admit(**kwargs):
            (self.root / 'input/raw.jsonl').write_bytes(b'forged')
            return original(**kwargs)
        with patch.object(pipeline, 'admit', side_effect=mutate_then_admit):
            report = self.run_admit()
        self.assertEqual(report['source_artifact_sha256'], sha(self.raw))
