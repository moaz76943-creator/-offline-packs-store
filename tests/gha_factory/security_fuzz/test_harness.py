"""Finite security QA contract tests; no release artifacts leave a temp directory."""
import base64
import gzip
import json
import random
import sqlite3
import tempfile
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.gha_factory.security_fuzz import harness


class HarnessTests(unittest.TestCase):
    def test_bounded_seeded_envelope_cases_and_failure_evidence(self):
        a = harness.run_family('envelope', seed=1234, max_cases=16)
        b = harness.run_family('envelope', seed=1234, max_cases=16)
        self.assertEqual(a, b)
        self.assertEqual(a['cases_executed'], 16)
        self.assertEqual(a['failures'], 0)
        self.assertFalse(a['publication_approved'])
        self.assertEqual(a['cases'][0]['status'], 'PASS')

    def test_reuses_canonical_sqlite_and_checks_primary_key(self):
        result = harness.run_family('sqlite')
        self.assertEqual(result['failures'], 0, result)
        self.assertEqual(result['cases_executed'], 8)

    def test_provenance_findings_never_mark_publication_ready(self):
        result = harness.run_family('provenance')
        self.assertFalse(result['publication_approved'])
        self.assertEqual(result['failures'], 0, result)
        self.assertEqual(result['cases_executed'], 6)

    def test_duplicate_id_probe_reaches_validator_with_duplicate_rows(self):
        fixture = harness.CandidateTests()
        fixture.setUp()
        try:
            def inspect(archive, _language, **_kwargs):
                env = json.loads(gzip.decompress(archive))
                sqlite_bytes = base64.b64decode(
                    harness._member(env, 'content/content.sqlite')['contentBase64'])
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'malicious.sqlite'
                    path.write_bytes(sqlite_bytes)
                    with sqlite3.connect(path) as db:
                        duplicate_rows = db.execute(
                            'SELECT id, COUNT(*) FROM lexicon GROUP BY id HAVING COUNT(*) > 1'
                        ).fetchall()
                    self.assertTrue(duplicate_rows, 'probe must contain duplicated IDs')
                raise harness.rc.ReleaseError('synthetic validator rejection')

            with patch.object(harness.rc, 'inspect_archive', side_effect=inspect) as called:
                actual = harness._attempt('duplicate_lexical_id', fixture, random.Random(1))
            self.assertEqual(actual, 'REJECTED')
            called.assert_called_once()
        finally:
            fixture.doCleanups()

    def test_unexpected_probe_crash_counts_as_failed_evidence(self):
        def synthetic_attempt(name, _fixture, _rng):
            if name == 'duplicate_json_key':
                raise RuntimeError('synthetic probe crash')
            return 'ACCEPTED' if name == 'baseline' else 'REJECTED'

        with patch.object(harness, '_attempt', side_effect=synthetic_attempt):
            result = harness.run_family('envelope', max_cases=14)
        case = next(c for c in result['cases'] if c['case'] == 'duplicate_json_key')
        self.assertEqual(case['actual'], 'CRASH')
        self.assertEqual(case['status'], 'FAIL')
        self.assertEqual(result['failures'], 1)
        self.assertNotIn('duplicate_json_key', result['security_findings'])
        self.assertFalse(result['publication_approved'])

    def test_signature_checks_use_no_private_keys(self):
        result = harness.run_family('signature')
        self.assertEqual(result['cases_executed'], 4)
        self.assertEqual(result['failures'], 0, result)

    def test_last_known_good_preserved_and_expansion_bounded(self):
        result = harness.run_family('staging')
        self.assertEqual(result['cases_executed'], 5)
        self.assertEqual(result['failures'], 0, result)

    def test_inner_metadata_adversarial_cases_reach_target_validator(self):
        fixture = harness.CandidateTests()
        fixture.setUp()
        try:
            def inspect(archive, _language, **_kwargs):
                env = json.loads(gzip.decompress(archive))
                content = base64.b64decode(
                    harness._member(env, 'content/content.json')['contentBase64'])
                meta = harness._json_member(env, 'metadata/pack.json')
                self.assertEqual(meta['contentMetadataSha256'], harness.rc.digest(content))
                raise harness.rc.ReleaseError('synthetic rejection after matching outer digest')

            with patch.object(harness.rc, 'inspect_archive', side_effect=inspect):
                for name in ('wrong_sha256', 'missing_sources'):
                    with self.subTest(name=name):
                        self.assertEqual(
                            harness._attempt(name, fixture, random.Random(1)),
                            'REJECTED')
        finally:
            fixture.doCleanups()

    def test_rejects_unbounded_campaigns(self):
        for family, bound in [('not-a-family', 1), ('envelope', 0), ('envelope', 999)]:
            with self.subTest(family=family, bound=bound):
                with self.assertRaises(ValueError):
                    harness.run_family(family, max_cases=bound)


if __name__ == '__main__':
    unittest.main()
