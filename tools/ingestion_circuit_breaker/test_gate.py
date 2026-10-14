import json
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch
import io
import sys

try:
    from tools.ingestion_circuit_breaker.gate import process, parse_args, sha256_file
except ImportError:
    from gate import process, parse_args, sha256_file

class TestGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.ledger_dir = self.root / 'legal' / 'ledger'
        self.ledger_dir.mkdir(parents=True)
        self.ledger_file = self.ledger_dir / 'sources.json'

        self.q_dir = self.root / 'quarantine'

        # Valid source artifact
        self.artifact_path = self.root / 'artifact.json'
        self.artifact_path.write_text('{"data": "valid"}')
        self.valid_hash = sha256_file(self.artifact_path)

        self.ledger_data = {
            "schema_version": "1.0.0",
            "sources": [
                {
                    "source_id": "test-source-1",
                    "retrieval": {
                        "sha256": self.valid_hash
                    },
                    "license": {
                        "id": "CC-BY-SA-4.0"
                    }
                },
                {
                    "source_id": "test-source-cc0",
                    "retrieval": {
                        "sha256": self.valid_hash
                    },
                    "license": {
                        "id": "CC0-1.0"
                    }
                }
            ]
        }
        self.ledger_file.write_text(json.dumps(self.ledger_data))

        self.manifest_file = self.root / 'manifest.json'

    def tearDown(self):
        self.tmp.cleanup()

    def run_process(self, manifest_dict):
        self.manifest_file.write_text(json.dumps(manifest_dict))
        args = parse_args(['--repo-root', str(self.root), '--manifest', str(self.manifest_file), '--quarantine', str(self.q_dir)])

        # Capture stdout and stderr
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            code, errors = process(args)
        return code, errors, stdout.getvalue(), stderr.getvalue()

    def test_valid_content(self):
        manifest = {
            "source_id": "test-source-1",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "intended_output_license": "CC-BY-SA-4.0",
            "destination": "packs/out"
        }
        code, errors, stdout, _ = self.run_process(manifest)
        self.assertEqual(code, 0)
        self.assertEqual(errors, [])
        admission = json.loads(stdout)
        self.assertEqual(admission["status"], "ADMITTED")

    def test_missing_license(self):
        manifest = {
            "source_id": "test-source-1",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "destination": "packs/out"
        }
        code, errors, _, _ = self.run_process(manifest)
        self.assertEqual(code, 2)
        self.assertIn("MISSING_OUTPUT_LICENSE", errors)

    def test_altered_bytes(self):
        # Change file content
        self.artifact_path.write_text('{"data": "invalid"}')
        manifest = {
            "source_id": "test-source-1",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "intended_output_license": "CC-BY-SA-4.0",
            "destination": "packs/out"
        }
        code, errors, _, _ = self.run_process(manifest)
        self.assertEqual(code, 2)
        self.assertIn("HASH_MISMATCH_MANIFEST", errors)

    def test_incompatible_obligations(self):
        # CC0 to Public Domain is forbidden per ledger rules
        manifest = {
            "source_id": "test-source-cc0",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "intended_output_license": "PUBLIC-DOMAIN",
            "destination": "packs/out"
        }
        code, errors, _, _ = self.run_process(manifest)
        self.assertEqual(code, 2)
        self.assertIn("LICENSE_CONFLICT", errors)

    def test_quarantine(self):
        manifest = {
            "source_id": "unknown-source",
        }
        code, errors, _, _ = self.run_process(manifest)
        self.assertEqual(code, 2)
        self.assertTrue(self.q_dir.exists())
        reasons = list(self.q_dir.glob("*.reason.txt"))
        self.assertEqual(len(reasons), 1)
        self.assertIn("UNKNOWN_SOURCE", reasons[0].read_text())

    def test_expired_token(self):
        manifest = {
            "source_id": "test-source-1",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "intended_output_license": "CC-BY-SA-4.0",
            "destination": "packs/out",
            "token_expiration": time.time() - 1000 # Past timestamp
        }
        code, errors, _, _ = self.run_process(manifest)
        self.assertEqual(code, 2)
        self.assertIn("EXPIRED_TOKEN", errors)

    def test_revoked_admission(self):
        manifest = {
            "source_id": "test-source-1",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "intended_output_license": "CC-BY-SA-4.0",
            "destination": "packs/out",
            "admission_revoked": True
        }
        code, errors, _, _ = self.run_process(manifest)
        self.assertEqual(code, 2)
        self.assertIn("REVOKED_ADMISSION", errors)

    def test_unavailable_interfaces_blocked_integration(self):
        manifest = {
            "requires_unavailable_interfaces": True
        }
        code, errors, _, stderr = self.run_process(manifest)
        self.assertEqual(code, 3)
        self.assertIn("BLOCKED_INTEGRATION", errors)
        self.assertIn("BLOCKED_INTEGRATION", stderr)

if __name__ == '__main__':
    unittest.main()
