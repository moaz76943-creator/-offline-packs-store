"""Adversarial rights research gate tests. No real downloads or source admission."""
import copy
import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from tools.factory_extensions.source_rights_research import audit as a


class FakeResponse:
    def __init__(self, url, body=b'<html>project license</html>', ctype='text/html'):
        self.url, self.buffer = url, BytesIO(body)
        self.headers = {'Content-Type': ctype}

    def geturl(self):
        return self.url

    def read(self, n):
        return self.buffer.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.buffer.close()


class FakeOpener:
    def open(self, req, timeout=None):
        return FakeResponse(req.full_url)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = a.load(a.CATALOG)
        cls.registry = a.load(a.REGISTRY)
        cls.ledger = a.load(a.LEDGER)

    def audit(self, registry=None, catalog=None, ledger=None):
        return a.audit(catalog or self.catalog, registry or self.registry,
                       self.ledger if ledger is None else ledger)

    def mutated(self):
        return copy.deepcopy(self.registry)

    def test_100_canonical_id_coverage_no_fabricated_capacity(self):
        report = self.audit()
        self.assertEqual(report['canonical_language_count'], 100)
        self.assertEqual(len({v['language_id'] for v in report['language_coverage']}), 100)
        self.assertTrue(all(x['resource_scarcity'] == 'NOT_MEASURED'
                            and x['redistribution_approved_sources'] == 0
                            for x in report['language_coverage']))

    def test_source_ledger_separate_and_empty(self):
        self.assertEqual(self.ledger['sources'], [])
        report = self.audit()
        self.assertEqual(report['approved_by_this_tool'], 0)
        self.assertEqual(report['route05_approved_existing_count'], 0)

    def test_each_candidate_has_human_blockers(self):
        report = self.audit()
        self.assertEqual(len(report['human_approval_queue']), 9)
        self.assertTrue(all('MISSING_AUTHORIZED_HUMAN_REDISTRIBUTION_DECISION' in x['blockers']
                            and not x['commercial_redistribution_allowed']
                            for x in report['human_approval_queue']))

    def test_all_required_source_categories_present(self):
        present = {x['kind'] for x in self.registry['candidates']}
        self.assertEqual(present, a.KIND)

    def test_explicit_german_coverage_is_research_only(self):
        report = self.audit()
        de = next(x for x in report['language_coverage'] if x['language_id'] == 'de')
        self.assertEqual(de['mapped_research_candidates'], ['unimorph-german'])
        self.assertEqual(de['source_bytes_verified'], 0)

    def test_panlex_cc0_does_not_override_source_conflict(self):
        report = self.audit()
        panlex = next(x for x in report['human_approval_queue'] if x['candidate_id'] == 'panlex')
        self.assertIn('PANLEX_CONFLICTING_ORIGINAL_SOURCE_RIGHTS', panlex['blockers'])
        self.assertIn('MULTI_LICENSE_OR_RECORD_RIGHTS_REVIEW', panlex['blockers'])

    def test_wiktionary_dual_and_sharealike_detected(self):
        rec = self.registry['candidates'][0]
        self.assertIn('SHAREALIKE_AND_ATTRIBUTION_REVIEW', a.warnings(rec))
        self.assertIn('MULTI_LICENSE_OR_RECORD_RIGHTS_REVIEW', a.warnings(rec))

    def test_noncommercial_claim_is_not_ignored(self):
        rec = copy.deepcopy(self.registry['candidates'][0])
        rec['source_license_claim'] = 'CC-BY-NC-4.0'
        self.assertIn('NONCOMMERCIAL_REQUIRES_REJECTION_OR_WRITTEN_EXCEPTION', a.warnings(rec))

    def test_missing_license_scope_flagged(self):
        rec = copy.deepcopy(self.registry['candidates'][0])
        rec['source_license_claim'] = 'UNKNOWN'
        self.assertIn('RIGHTS_SCOPE_INCOMPLETE', a.warnings(rec))

    def test_audio_recording_requires_separate_authorization(self):
        rec = next(x for x in self.registry['candidates'] if x['candidate_id'] == 'tatoeba-audio')
        self.assertIn('AUDIO_AND_SPEAKER_RIGHTS_REVIEW', a.warnings(rec))

    def test_reject_registry_preapproved_list(self):
        data = self.mutated()
        data['approved_sources'] = ['panlex']
        with self.assertRaisesRegex(ValueError, 'cannot approve'):
            self.audit(data)

    def test_reject_fabricated_reviewer(self):
        data = self.mutated()
        data['candidates'][0]['human_review']['status'] = 'APPROVED_FOR_REDISTRIBUTION'
        with self.assertRaisesRegex(ValueError, 'cannot auto-approve'):
            self.audit(data)

    def test_reject_commercial_authorization(self):
        data = self.mutated()
        data['candidates'][0]['commercial_redistribution'] = 'YES'
        with self.assertRaisesRegex(ValueError, 'cannot grant'):
            self.audit(data)

    def test_reject_duplicate_candidate(self):
        data = self.mutated()
        data['candidates'].append(copy.deepcopy(data['candidates'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.audit(data)

    def test_reject_unknown_language(self):
        data = self.mutated()
        data['candidates'][0]['confirmed_language_ids'] = ['xx']
        with self.assertRaisesRegex(ValueError, 'unverified language'):
            self.audit(data)

    def test_reject_duplicate_language(self):
        data = self.mutated()
        data['candidates'][2]['confirmed_language_ids'] = ['de', 'de']
        with self.assertRaisesRegex(ValueError, 'unverified language'):
            self.audit(data)

    def test_reject_candidate_id_collision_with_approved_route05(self):
        ledger = {'schema_version': '1.0.0',
                  'sources': [{'source_id': 'panlex', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]}
        queue = self.audit(ledger=ledger)['human_approval_queue']
        panlex = next(x for x in queue if x['candidate_id'] == 'panlex')
        self.assertIn('EXISTING_LEDGER_ID_COLLISION_CHECK_REQUIRED', panlex['blockers'])

    def test_reject_malformed_json_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'duplicate.json'
            path.write_text('{"sources":[],"sources":[]}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                a.load(path)

    def test_reject_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'bad.json'
            path.write_text('{"value":NaN}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'nonfinite'):
                a.load(path)

    def test_source_and_license_urls_are_https_allowlisted(self):
        for url in ('http://panlex.org/license', 'https://127.0.0.1/secrets',
                    'https://panlex.org@evil.example/license',
                    'https://panlex.org/license#x', 'https://evil.example/test',
                    'https://panlex.org/license?token=abc'):
            self.assertFalse(a.valid_url(url), url)
        self.assertTrue(a.valid_url('https://panlex.org/license'))

    def test_reject_forged_evidence_hash_without_snapshot_path(self):
        data = self.mutated()
        data['candidates'][0]['evidence'][0]['snapshot_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'path/hash'):
            self.audit(data)

    def test_reject_invalid_dataset_hash(self):
        data = self.mutated()
        data['candidates'][0]['dataset_sha256'] = 'not-a-digest'
        with self.assertRaisesRegex(ValueError, 'dataset digest'):
            self.audit(data)

    def test_no_crawling_during_core_audit(self):
        before = a.LEDGER.read_bytes()
        self.audit()
        self.assertEqual(a.LEDGER.read_bytes(), before)

    def test_snapshotter_hashes_bytes_but_never_approves(self):
        one = self.mutated()
        one['candidates'] = one['candidates'][:1]
        with tempfile.TemporaryDirectory() as d:
            output = a.capture_public_evidence(one, d, FakeOpener())
            self.assertEqual(output[0]['sha256'], hashlib.sha256(
                b'<html>project license</html>').hexdigest())
            self.assertEqual(output[0]['status'], 'SNAPSHOT_ONLY')
            self.assertFalse('APPROVED_FOR_REDISTRIBUTION' in json.dumps(output))

    def test_snapshotter_rejects_redirects(self):
        class Redirecting:
            def open(self, req, timeout=None):
                return FakeResponse('https://evil.example/redirect')
        one = self.mutated()
        one['candidates'] = one['candidates'][:1]
        with tempfile.TemporaryDirectory() as d:
            out = a.capture_public_evidence(one, d, Redirecting())
            self.assertEqual(out[0]['status'], 'UNAVAILABLE')

    def test_snapshotter_rejects_oversized_pages(self):
        class Large:
            def open(self, req, timeout=None):
                return FakeResponse(req.full_url, b'x' * (a.MAX_EVIDENCE + 1))
        one = self.mutated()
        one['candidates'] = one['candidates'][:1]
        with tempfile.TemporaryDirectory() as d:
            out = a.capture_public_evidence(one, d, Large())
            self.assertEqual(out[0]['status'], 'UNAVAILABLE')

    def test_snapshotter_rejects_binary_content(self):
        class Binary:
            def open(self, req, timeout=None):
                return FakeResponse(req.full_url, b'\0', 'application/octet-stream')
        one = self.mutated()
        one['candidates'] = one['candidates'][:1]
        with tempfile.TemporaryDirectory() as d:
            out = a.capture_public_evidence(one, d, Binary())
            self.assertEqual(out[0]['status'], 'UNAVAILABLE')

    def test_daily_ledger_never_modified_by_cli(self):
        before = a.LEDGER.read_bytes()
        with tempfile.TemporaryDirectory() as d:
            a.main(['--out', d])
            out = json.loads((Path(d) / 'rights_audit.json').read_text(encoding='utf-8'))
            self.assertEqual(out['approved_by_this_tool'], 0)
        self.assertEqual(a.LEDGER.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
