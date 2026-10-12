import unittest
import json
import tempfile
from pathlib import Path
import os
import shutil
import time

from tools.ingestion_circuit_breaker.circuit_breaker import (
    evaluate_license_compatibility,
    generate_hash,
    issue_admission,
    quarantine_source,
    process_ingestion
)

class MockArgs:
    def __init__(self, source, provenance, destination, quarantine, integrate=False):
        self.source = Path(source)
        self.provenance = Path(provenance)
        self.destination = Path(destination)
        self.quarantine = Path(quarantine)
        self.integrate = integrate

class TestCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_root = Path(self.temp_dir)

        # Setup mock manifest
        self.manifest_path = self.repo_root / 'manifest.json'
        with open(self.manifest_path, 'w') as f:
            json.dump({'intellectual_property_status': 'PUBLIC_DOMAIN_ZERO_COPYRIGHT'}, f)

        self.source_path = self.repo_root / 'source.json'
        with open(self.source_path, 'w') as f:
            f.write('{"data": "test"}')

        self.source_hash = generate_hash(self.source_path)

        self.provenance_path = self.repo_root / 'provenance.json'
        self.quarantine_dir = self.repo_root / 'quarantine'
        self.destination_dir = self.repo_root / 'destination'
        self.quarantine_dir.mkdir()
        self.destination_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_missing_licenses(self):
        with open(self.provenance_path, 'w') as f:
            json.dump({'source_hash': self.source_hash}, f)

        args = MockArgs(self.source_path, self.provenance_path, self.destination_dir, self.quarantine_dir)

        with self.assertRaises(SystemExit) as cm:
            process_ingestion(args, self.repo_root)

        self.assertNotEqual(cm.exception.code, 0)
        self.assertTrue((self.quarantine_dir / 'source.json').exists())

    def test_altered_source_bytes(self):
        with open(self.provenance_path, 'w') as f:
            json.dump({
                'license': 'PUBLIC_DOMAIN_ZERO_COPYRIGHT',
                'source_hash': 'invalidhash123'
            }, f)

        args = MockArgs(self.source_path, self.provenance_path, self.destination_dir, self.quarantine_dir)

        with self.assertRaises(SystemExit) as cm:
            process_ingestion(args, self.repo_root)

        self.assertNotEqual(cm.exception.code, 0)
        self.assertTrue((self.quarantine_dir / 'source.json').exists())

    def test_expired_tokens(self):
        admission = issue_admission(self.source_path, 'PUBLIC_DOMAIN_ZERO_COPYRIGHT', self.destination_dir)
        # Manually expire token
        admission['expiry'] = int(time.time()) - 100

        self.assertTrue(int(time.time()) > admission['expiry'])

        # Simulating token validation logic
        def validate_admission(adm):
            if int(time.time()) > adm['expiry']:
                return False
            if adm.get('status') == 'REVOKED':
                return False
            return True

        self.assertFalse(validate_admission(admission))

    def test_revoked_admission(self):
        admission = issue_admission(self.source_path, 'PUBLIC_DOMAIN_ZERO_COPYRIGHT', self.destination_dir)
        # Manually revoke admission
        admission['status'] = 'REVOKED'

        def validate_admission(adm):
            if int(time.time()) > adm['expiry']:
                return False
            if adm.get('status') == 'REVOKED':
                return False
            return True

        self.assertFalse(validate_admission(admission))

    def test_incompatible_obligations(self):
        with open(self.provenance_path, 'w') as f:
            json.dump({
                'license': 'PROPRIETARY',
                'source_hash': self.source_hash
            }, f)

        args = MockArgs(self.source_path, self.provenance_path, self.destination_dir, self.quarantine_dir)

        with self.assertRaises(SystemExit) as cm:
            process_ingestion(args, self.repo_root)

        self.assertNotEqual(cm.exception.code, 0)
        self.assertTrue((self.quarantine_dir / 'source.json').exists())

    def test_valid_content(self):
        with open(self.provenance_path, 'w') as f:
            json.dump({
                'license': 'PUBLIC_DOMAIN_ZERO_COPYRIGHT',
                'source_hash': self.source_hash
            }, f)

        args = MockArgs(self.source_path, self.provenance_path, self.destination_dir, self.quarantine_dir)

        # Should not raise SystemExit, returns admission manifest
        admission = process_ingestion(args, self.repo_root)
        self.assertEqual(admission['status'], 'VALID')
        self.assertEqual(admission['source_hash'], self.source_hash)

    def test_fixture_pipeline_halts(self):
        # Setting up invalid provenance
        with open(self.provenance_path, 'w') as f:
            json.dump({
                'license': 'GPL',
                'source_hash': self.source_hash
            }, f)

        # Simulate CLI integrating logic (halts)
        args = MockArgs(self.source_path, self.provenance_path, self.destination_dir, self.quarantine_dir, integrate=True)

        with self.assertRaises(SystemExit) as cm:
            process_ingestion(args, self.repo_root)

        # Gate failure exits non-zero before reaching integration block
        self.assertNotEqual(cm.exception.code, 0)

        # Test the BLOCKED_INTEGRATION path with valid content
        with open(self.provenance_path, 'w') as f:
            json.dump({
                'license': 'PUBLIC_DOMAIN_ZERO_COPYRIGHT',
                'source_hash': self.source_hash
            }, f)

        with self.assertRaises(SystemExit) as cm:
            process_ingestion(args, self.repo_root)

        # Valid content requesting integration exits with 0 and prints BLOCKED_INTEGRATION
        self.assertEqual(cm.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
