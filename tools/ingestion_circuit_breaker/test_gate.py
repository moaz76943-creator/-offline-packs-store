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
    from tools.ingestion_circuit_breaker.pipeline import run_fixture_pipeline
except ImportError:
    from gate import process, parse_args, sha256_file
    from pipeline import run_fixture_pipeline

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
        self.assertGreaterEqual(admission["expires_at"], int(time.time()))
        self.assertLessEqual(admission["expires_at"], int(time.time()) + 300)

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

    def test_fixture_ingestion_pipeline_halts_on_gate_failure(self):
        import subprocess
        gate_script = Path(__file__).parent / 'gate.py'
        marker = self.root / 'fixture_ingestion_executed.txt'
        fixture_runner = self.root / 'fixture_pipeline.py'
        # The real integration is not present; prove the fixture runner stops
        # on a denied gate and does advance after a successful gate.
        fixture_runner.write_text(
            "import subprocess, sys\n"
            "from pathlib import Path\n"
            "gate = subprocess.run(sys.argv[1:-1])\n"
            "if gate.returncode: sys.exit(gate.returncode)\n"
            "Path(sys.argv[-1]).write_text('executed')\n"
        )
        cmd = [
            sys.executable, str(fixture_runner),
            sys.executable, str(gate_script),
            '--repo-root', str(self.root),
            '--manifest', str(self.manifest_file),
            '--quarantine', str(self.q_dir),
            str(marker),
        ]

        self.manifest_file.write_text(json.dumps({'source_id': 'unknown-source'}))
        denied = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(denied.returncode, 2)
        self.assertIn('BLOCK: UNKNOWN_SOURCE', denied.stderr)
        self.assertFalse(marker.exists())
        reasons = list(self.q_dir.glob('*.reason.txt'))
        self.assertEqual(len(reasons), 1)
        self.assertIn('UNKNOWN_SOURCE', reasons[0].read_text())

        self.manifest_file.write_text(json.dumps({
            'source_id': 'test-source-1',
            'artifact_path': 'artifact.json',
            'artifact_sha256': self.valid_hash,
            'intended_output_license': 'CC-BY-SA-4.0',
        }))
        accepted = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertTrue(marker.exists())


    def test_direct_fixture_pipeline_uses_same_admission_gate(self):
        manifest = {
            "source_id": "test-source-1",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "intended_output_license": "CC-BY-SA-4.0",
        }
        target = self.root / "out" / "admitted.json"
        self.manifest_file.write_text(json.dumps(manifest))
        args = parse_args(["--repo-root", str(self.root),
                           "--manifest", str(self.manifest_file),
                           "--quarantine", str(self.q_dir)])
        code, errors, published = run_fixture_pipeline(args, target, b'{"ok":true}')
        self.assertEqual((code, errors, published), (0, [], True))
        self.assertEqual(target.read_bytes(), b'{"ok":true}')


    def test_unsupported_source_and_output_licenses_stay_blocked(self):
        for source_license, output_license, expected in (
            ('CC0-1.0', 'GPL-3.0', 'UNSUPPORTED_OUTPUT_LICENSE'),
            ('CC-BY-2.0-FR', 'unverified-license', 'UNSUPPORTED_OUTPUT_LICENSE'),
            ('CC-BY-2.0-FR', 'GFDL-1.3-only', 'LICENSE_CONVERSION_REVIEW_REQUIRED'),
            ('GPL-3.0', 'CC0-1.0', 'UNSUPPORTED_SOURCE_LICENSE'),
        ):
            with self.subTest(source_license=source_license, output_license=output_license):
                self.ledger_data['sources'][1]['license']['id'] = source_license
                self.ledger_file.write_text(json.dumps(self.ledger_data))
                code, errors, stdout, _ = self.run_process({
                    'source_id': 'test-source-cc0', 'artifact_path': 'artifact.json',
                    'artifact_sha256': self.valid_hash,
                    'intended_output_license': output_license, 'destination': 'packs/out',
                })
                self.assertEqual(code, 2)
                self.assertIn(expected, errors)
                self.assertNotIn('ADMITTED', stdout)

    def test_sublicense_permissive_to_copyleft(self):
        # Permissive license with obligations (e.g. CC-BY-2.0-FR) sublicensed to copyleft should be allowed
        self.ledger_data["sources"].append({
            "source_id": "test-source-permissive",
            "retrieval": {
                "sha256": self.valid_hash
            },
            "license": {
                "id": "CC-BY-2.0-FR"
            }
        })
        self.ledger_file.write_text(json.dumps(self.ledger_data))

        manifest = {
            "source_id": "test-source-permissive",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "intended_output_license": "CC-BY-SA-4.0",
            "destination": "packs/out"
        }
        code, errors, _, _ = self.run_process(manifest)
        self.assertEqual(code, 0)
        self.assertEqual(errors, [])

    def test_sublicense_obligations_to_public_domain(self):
        # License with obligations (e.g. CC-BY-2.0-FR) cannot be sublicensed to PUBLIC-DOMAIN or CC0-1.0
        self.ledger_data["sources"].append({
            "source_id": "test-source-permissive",
            "retrieval": {
                "sha256": self.valid_hash
            },
            "license": {
                "id": "CC-BY-2.0-FR"
            }
        })
        self.ledger_file.write_text(json.dumps(self.ledger_data))

        manifest = {
            "source_id": "test-source-permissive",
            "artifact_path": "artifact.json",
            "artifact_sha256": self.valid_hash,
            "intended_output_license": "PUBLIC-DOMAIN",
            "destination": "packs/out"
        }
        code, errors, _, _ = self.run_process(manifest)
        self.assertEqual(code, 2)
        self.assertIn("LICENSE_CONFLICT", errors)

if __name__ == '__main__':
    unittest.main()
