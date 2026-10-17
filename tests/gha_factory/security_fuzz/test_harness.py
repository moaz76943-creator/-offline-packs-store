"""Finite security QA contract tests; no release artifacts leave a temp directory."""
import sys
import unittest
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

    def test_signature_checks_use_no_private_keys(self):
        result = harness.run_family('signature')
        self.assertEqual(result['cases_executed'], 4)
        self.assertEqual(result['failures'], 0, result)

    def test_last_known_good_preserved_and_expansion_bounded(self):
        result = harness.run_family('staging')
        self.assertEqual(result['cases_executed'], 5)
        self.assertEqual(result['failures'], 0, result)

    def test_rejects_unbounded_campaigns(self):
        for family, bound in [('not-a-family', 1), ('envelope', 0), ('envelope', 999)]:
            with self.subTest(family=family, bound=bound):
                with self.assertRaises(ValueError):
                    harness.run_family(family, max_cases=bound)


if __name__ == '__main__':
    unittest.main()
