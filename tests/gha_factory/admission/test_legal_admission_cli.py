"""The compatibility command must enforce the canonical rights gate."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.gha_factory.admission import legal_admission_validator as cli

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'tools/gha_factory/admission/legal_admission_validator.py'


class LegalAdmissionCliTests(unittest.TestCase):
    def test_rejected_source_returns_false_to_python_caller(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / 'sources.json'
            ledger.write_text(json.dumps({'schema_version': '1.0.0',
                                         'sources': [{'source_id': 'unapproved'}]}))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(cli.audit_sources_ledger(ledger))

    def test_legacy_cli_propagates_rights_denial(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / 'sources.json'
            ledger.write_text(json.dumps({'schema_version': '1.0.0',
                                         'sources': [{'source_id': 'unapproved'}]}))
            result = subprocess.run([sys.executable, str(SCRIPT), str(ledger)],
                                    capture_output=True, text=True, cwd=tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn('BLOCK', result.stdout)

    def test_malformed_json_fails_closed_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / 'sources.json'
            ledger.write_text('{')
            result = subprocess.run([sys.executable, str(SCRIPT), str(ledger)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    def test_flat_approval_is_rejected_by_canonical_contract(self):
        # Metadata shaped like the old proposal must not become rights evidence.
        source = dict(source_id='unapproved', canonical_url='https://example.org',
                      publisher='test-only', license_id='CC-BY-SA-4.0',
                      license_url='https://creativecommons.org/licenses/by-sa/4.0/',
                      allowed_uses=['educational'], attribution_required=True,
                      source_sha256='a' * 64, license_evidence_sha256='b' * 64,
                      review_decision='APPROVED', retrieval_date='2026-10-25')
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / 'sources.json'
            ledger.write_text(json.dumps({'schema_version': '1.0.0',
                                         'sources': [source]}))
            result = subprocess.run([sys.executable, str(SCRIPT), str(ledger)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('BLOCK', result.stdout)


if __name__ == '__main__':
    unittest.main()
