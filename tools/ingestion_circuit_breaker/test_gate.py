import json
import unittest
import tempfile
import shutil
import sys
import os
from pathlib import Path
from unittest.mock import patch
import hashlib
from datetime import datetime, timezone, timedelta

from tools.ingestion_circuit_breaker import gate

class TestGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.staging = self.root / "staging"
        self.source_path = self.root / "source.bin"
        self.manifest_path = self.root / "manifest.json"
        self.token_path = self.root / "token.json"

        self.source_content = b"test content"
        self.source_hash = hashlib.sha256(self.source_content).hexdigest()

        self.source_path.write_bytes(self.source_content)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_manifest(self, data):
        self.manifest_path.write_text(json.dumps(data))

    def test_valid_admission(self):
        self.write_manifest({
            "source_id": "test_src",
            "license_id": "CC-BY-SA-4.0",
            "output_license_id": "CC-BY-SA-4.0",
            "artifact_sha256": self.source_hash
        })

        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 0)

        admitted = list((self.staging / "admitted").glob("*.json"))
        self.assertEqual(len(admitted), 1)

    def test_missing_license(self):
        self.write_manifest({
            "source_id": "test_src",
            "license_id": "UNKNOWN",
            "output_license_id": "CC-BY-SA-4.0",
            "artifact_sha256": self.source_hash
        })

        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 1)
        self.assertTrue((self.staging / "quarantined").exists())

    def test_altered_bytes(self):
        self.write_manifest({
            "source_id": "test_src",
            "license_id": "CC-BY-SA-4.0",
            "output_license_id": "CC-BY-SA-4.0",
            "artifact_sha256": "badhash"
        })

        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 1)
        self.assertTrue((self.staging / "quarantined").exists())

    def test_incompatible_obligations(self):
        self.write_manifest({
            "source_id": "test_src",
            "license_id": "CC-BY-SA-4.0",
            "output_license_id": "GFDL-1.3-only",
            "artifact_sha256": self.source_hash
        })

        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 1)
        self.assertTrue((self.staging / "quarantined").exists())

    def test_invalid_source(self):
        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.root / "nonexistent.bin"),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 2)

    def test_public_domain_relicensing(self):
        self.write_manifest({
            "source_id": "test_src",
            "license_id": "CC0-1.0",
            "output_license_id": "PUBLIC-DOMAIN",
            "artifact_sha256": self.source_hash
        })

        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 1)

    def test_fixture_pipeline_halts(self):
        # ensure it halts on gate failure
        self.write_manifest({
            "source_id": "test_src",
            "license_id": "CC-BY-SA-4.0",
            "output_license_id": "CC-BY-SA-4.0",
            "artifact_sha256": "badhash"
        })
        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 1)
        self.assertFalse((self.staging / "admitted").exists())

    def test_revoked_admission(self):
        # Test 1: Successful admission
        self.write_manifest({
            "source_id": "test_src",
            "license_id": "CC-BY-SA-4.0",
            "output_license_id": "CC-BY-SA-4.0",
            "artifact_sha256": self.source_hash
        })
        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 0)

        # Simulating changes (artifact mutated)
        new_source_content = b"new content"
        self.source_path.write_bytes(new_source_content)
        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging)])
        self.assertEqual(ret, 1)

        # Test revoked token
        self.token_path.write_text(json.dumps({
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "status": "REVOKED"
        }))
        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging),
                             "--verify-token", str(self.token_path)])
        self.assertEqual(ret, 1)

    def test_expired_token(self):
        # Test expiration check
        admission_time = datetime.now(timezone.utc) - timedelta(hours=2)
        admission = {
            "issued_at": admission_time.isoformat(),
            "status": "ADMITTED"
        }
        self.token_path.write_text(json.dumps(admission))
        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging),
                             "--verify-token", str(self.token_path)])
        self.assertEqual(ret, 1)

        # Test valid unexpired token
        admission_time_valid = datetime.now(timezone.utc) - timedelta(minutes=30)
        admission_valid = {
            "issued_at": admission_time_valid.isoformat(),
            "status": "ADMITTED"
        }
        self.token_path.write_text(json.dumps(admission_valid))
        with patch('tools.ingestion_circuit_breaker.gate.check_repo_access'):
            ret = gate.main(["--source", str(self.source_path),
                             "--manifest", str(self.manifest_path),
                             "--staging-root", str(self.staging),
                             "--verify-token", str(self.token_path)])
        self.assertEqual(ret, 0)

    def test_missing_interface_returns_blocked_integration(self):
        import subprocess
        script_path = Path('tools/ingestion_circuit_breaker/test_import.py')
        script_path.write_text('''
import sys
import builtins
real_import = builtins.__import__
def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'legal.ledger.admission':
        raise ImportError("No module named 'legal.ledger.admission'")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = mock_import
try:
    import tools.ingestion_circuit_breaker.gate
except SystemExit as e:
    sys.exit(e.code)
''')
        env = os.environ.copy()
        env['PYTHONPATH'] = '.'
        result = subprocess.run([sys.executable, str(script_path)], capture_output=True, env=env)
        self.assertEqual(result.returncode, 3)
        self.assertIn(b"BLOCKED_INTEGRATION", result.stderr)
